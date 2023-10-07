
import os
import glob
import pickle
import argparse
from tqdm import tqdm
import nltk
from sklearn.preprocessing import normalize
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity
from nltk.corpus import stopwords, wordnet
from nltk.tokenize import word_tokenize
from nltk.stem import WordNetLemmatizer
from multiprocessing import Pool, cpu_count

import logging
from pdfminer.high_level import extract_text

from gensim.models import Doc2Vec
from gensim.models.doc2vec import TaggedDocument

PERCENTAGE_THRESHOLD = 0.1
TOP_DOCUMENTS = 5


class PDFProcessor:

    """Handles PDF extraction and text preprocessing."""

    @staticmethod
    def extract_text_by_page(file_path):
        """Extracts text content page by page from a PDF file."""
        texts = []
        try:
            full_text = extract_text(file_path).replace("\n", " ")
            texts = [text for text in full_text.split('\f')]
        except Exception as e:
            logging.error(f"Error extracting text from {file_path}: {e}")
        return texts

    @staticmethod
    def preprocess(text):
        """Preprocesses a given text."""
        tokens = [token.lower()
                  for token in word_tokenize(text) if token.isalpha()]
        stop_words = set(stopwords.words('english'))
        tokens = [token for token in tokens if token not in stop_words]
        lemmatizer = WordNetLemmatizer()
        pos_tags = nltk.pos_tag(tokens)
        tokens = [lemmatizer.lemmatize(token, PDFProcessor._get_wordnet_pos(
            pos_tag)) for token, pos_tag in pos_tags]
        return ' '.join(tokens)

    @staticmethod
    def _get_wordnet_pos(tag):
        """Maps POS tag to first character used by WordNetLemmatizer."""
        tag_dict = {
            "J": wordnet.ADJ,
            "N": wordnet.NOUN,
            "V": wordnet.VERB,
            "R": wordnet.ADV
        }
        return tag_dict.get(tag[0].upper(), wordnet.NOUN)


class Doc2VecProcessor:
    """Handles Doc2Vec related functionalities."""

    @staticmethod
    def train_doc2vec_model(docs, vector_size=35, window=5, min_count=2, workers=4, epochs=50):
        """Train a Doc2Vec model with the provided documents."""
        tagged_data = [TaggedDocument(words=word_tokenize(_d.lower()), tags=[
                                      str(i)]) for i, _d in enumerate(docs)]
        model = Doc2Vec(vector_size=vector_size, window=window,
                        min_count=min_count, workers=workers)
        model.build_vocab(tagged_data)
        model.train(tagged_data, total_examples=model.corpus_count,
                    epochs=epochs)
        return model

    @staticmethod
    def infer_vector(model, doc):
        """Infer vector for a document using a trained Doc2Vec model."""
        return model.infer_vector(word_tokenize(doc.lower()))


class IndexBuilder:
    """Handles index building operations."""

    def __init__(self, mode="tfidf"):
        self.mode = mode

    def idf_sum_pca(self, tfidf_matrix, num_components=50):
        """
        Calculate IDF-sum and apply PCA for dimensionality reduction.

        Args:
            tfidf_matrix (scipy.sparse.csr_matrix): TF-IDF matrix of document text.
            num_components (int): Number of PCA components to retain.

        Returns:
            scipy.sparse.csr_matrix: TF-IDF matrix after IDF-sum and PCA.
        """
        # Calculate IDF-sum for each document
        idf_sums = tfidf_matrix.sum(axis=1).A1

        # Apply PCA for dimensionality reduction
        pca = TruncatedSVD(n_components=num_components)
        tfidf_sum_pca = pca.fit_transform(tfidf_matrix)

        return tfidf_sum_pca, idf_sums

    def _process_file(self, file_path):
        """Process a single file by extracting and preprocessing its text page by page."""
        pages = PDFProcessor.extract_text_by_page(file_path)
        return [PDFProcessor.preprocess(page) for page in pages]

    def build(self, directory_path, batch_size=1000):
        """Builds the index from a given directory of PDF files page by page."""
        file_paths = glob.glob(os.path.join(directory_path, '*.pdf'))

        # Create lists to store processed data
        processed_pages = []
        document_pages = []

        # Process files in chunks (batches)
        for i in range(0, len(file_paths), batch_size):
            batch_paths = file_paths[i: i + batch_size]
            with Pool(cpu_count()) as pool:
                # Process a batch of files in parallel and extract text by pages
                processed_pages_data = list(
                    tqdm(pool.imap(self._process_file, batch_paths), total=len(batch_paths)))

            # Update the lists with processed data from the current batch
            processed_pages.extend(
                [page for doc in processed_pages_data for page in doc])
            document_pages.extend(
                [(fp, idx) for fp, doc in zip(batch_paths, processed_pages_data) for idx in range(len(doc))])

        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(processed_pages)

        data = {
            'vectorizer': vectorizer,
            'document_pages': document_pages
        }

        if self.mode == "idf_sum_pca":
            # Use the idf_sum_pca method
            idf_sum_pca_matrix, idf_sums = self.idf_sum_pca(tfidf_matrix)
            data['idf_sum_pca_matrix'] = idf_sum_pca_matrix
            data['idf_sums'] = idf_sums
        elif self.mode == "lsi":
            lsi_model = TruncatedSVD(n_components=50)
            data['lsi_matrix'] = lsi_model.fit_transform(tfidf_matrix)
            data['lsi_model'] = lsi_model
        elif self.mode == "doc2vec":
            d2v_processor = Doc2VecProcessor()
            self.d2v_model = d2v_processor.train_doc2vec_model(processed_pages)
            data['d2v_model'] = self.d2v_model
            data['document_vectors'] = [self.d2v_model.dv[i]
                                        for i in range(len(processed_pages))]
        else:
            data['tfidf_matrix'] = tfidf_matrix

        return data


class SearchEngine:
    """Handles search functionalities."""

    def __init__(self, index_data, mode):
        self.mode = mode
        self.data = index_data
        if self.mode == 'doc2vec':
            self.d2v_model = index_data['d2v_model']

    def query(self, text, top_k=10):
        """Queries the search engine and retrieves relevant pages."""
        preprocessed_query = PDFProcessor.preprocess(text)

        if self.mode == "idf_sum_pca":
            query_vector = self.data['vectorizer'].transform(
                [preprocessed_query])
            idf_sum_query = query_vector.sum()

            # Ensure query_vector_pca is 2D, reshape if necessary
            query_vector_pca = self.data['idf_sum_pca_matrix']

            if query_vector_pca.ndim == 1:
                # If it's 1D, reshape it into a 2D array with one row
                query_vector_pca = query_vector_pca.reshape(1, -1)

            # Calculate cosine similarity with IDF-sum and PCA
            query_vector_pca_normalized = normalize(query_vector_pca)
            # Normalize IDF-sum-PCA matrix
            idf_sum_pca_matrix_normalized = normalize(
                self.data['idf_sum_pca_matrix'])

            # Calculate cosine similarity with normalized vectors
            similarities = cosine_similarity(
                query_vector_pca_normalized, idf_sum_pca_matrix_normalized)

            # Extract the similarity scores
            similarities = similarities[0]

        elif self.mode == "lsi":
            query_vector = self.data['vectorizer'].transform(
                [preprocessed_query])
            lsi_query_vector = self.data['lsi_model'].transform(query_vector)
            similarities = cosine_similarity(
                self.data['lsi_matrix'], lsi_query_vector).flatten()
        elif self.mode == "doc2vec":
            query_vector = Doc2VecProcessor.infer_vector(
                self.d2v_model, preprocessed_query)
            scores = cosine_similarity(
                [query_vector], self.data['document_vectors'])
            similarities = scores[0]
        else:
            query_vector = self.data['vectorizer'].transform(
                [preprocessed_query])
            similarities = cosine_similarity(
                self.data['tfidf_matrix'], query_vector).flatten()

        top_indices = similarities.argsort()[:-top_k - 1:-1]
        scores = similarities[top_indices]
        paths = [(self.data['document_pages'][index][0],
                  self.data['document_pages'][index][1]) for index in top_indices]

        # Calculate total number of pages for each document
        total_pages_per_doc = {}
        for doc, page in self.data['document_pages']:
            total_pages_per_doc[doc] = total_pages_per_doc.get(doc, 0) + 1

        # Aggregate the similarity scores for each document
        doc_similarity_aggregate = {}
        for index in similarities.argsort()[:-int(PERCENTAGE_THRESHOLD * len(similarities)) - 1:-1]:
            doc_path = self.data['document_pages'][index][0]
            # Aggregate the similarity score for the document
            doc_similarity_aggregate[doc_path] = doc_similarity_aggregate.get(
                doc_path, 0) + similarities[index]

        # Normalize the similarity score aggregate by total number of pages
        normalized_similarity = {}
        for doc, aggregate_score in doc_similarity_aggregate.items():
            normalized_similarity[doc] = aggregate_score / \
                total_pages_per_doc[doc]

        # Sort documents by normalized similarity
        sorted_docs = sorted(normalized_similarity.items(),
                             key=lambda kv: kv[1], reverse=True)

        return paths, scores, sorted_docs[:TOP_DOCUMENTS]


def save_index(index_file, data):
    """Save index data to a file."""
    with open(index_file, 'wb') as f:
        pickle.dump(data, f)


def load_index(index_file):
    """Load index data from a file."""
    with open(index_file, 'rb') as f:
        return pickle.load(f)


def get_multiline_input(prompt, end_keyword="END"):
    """Get multiline input from the user until the end keyword is entered."""
    print(prompt, f"(Type '{end_keyword}' on a new line to finish)")
    lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == end_keyword:
                break
            lines.append(line)
        except EOFError:  # This handles Ctrl+D
            break
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Build an index and search PDFs.")
    parser.add_argument(
        '--index', type=str, default='index_data.pkl', help='Path to the index file.')
    parser.add_argument('--docs', type=str, default='docs',
                        help='Path to the directory containing PDF documents.')
    parser.add_argument('--update-index', action='store_true',
                        help='Update the index if it already exists.')
    parser.add_argument('--mode', type=str, choices=['tfidf', 'lsi', 'doc2vec', 'idf_sum_pca'], default='tfidf',
                        help='The indexing and search mode.')
    args = parser.parse_args()

    # Check if index file exists
    if os.path.exists(args.index) and not args.update_index:
        print("Loading existing index...")
        index_data = load_index(args.index)
    else:
        print("Building new index...")
        indexer = IndexBuilder(args.mode)
        index_data = indexer.build(args.docs)
        save_index(args.index, index_data)
        print(f"Index saved to {args.index}")

    search_engine = SearchEngine(index_data, args.mode)

    while True:
        query = get_multiline_input("Enter your search query")

        if not query.strip():  # If the user just presses enter without any input
            print("Empty query, please try again or type 'exit' to stop.")
            continue

        if query.strip().lower() == 'exit':
            break

        results, scores, sorted_docs = search_engine.query(query)
        print("Top pages with highest similarity score:")
        for i, (path, page) in enumerate(results):
            print(
                f"Document: {path}, Page: {page + 1}, Score: {scores[i]:.4f}")

        print("Top 5 relevant documents:")
        for doc, count in sorted_docs:
            print(f"Document: {doc}, Cumulative Score: {count}")


if __name__ == "__main__":
    main()
