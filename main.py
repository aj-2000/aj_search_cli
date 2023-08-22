import argparse
import PyPDF2
import nltk
from nltk.corpus import stopwords, wordnet
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer, WordNetLemmatizer
import glob
import os
from sklearn.feature_extraction.text import TfidfVectorizer
import pickle
from tqdm import tqdm
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics.pairwise import cosine_similarity

# Initialize NLTK's resources and download required data
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('wordnet')
nltk.download('averaged_perceptron_tagger')

num_topics = 5

def get_wordnet_pos(tag):
    """Map POS tag to first character used by WordNetLemmatizer"""
    tag = tag[0].upper()
    tag_dict = {"J": wordnet.ADJ,
                "N": wordnet.NOUN,
                "V": wordnet.VERB,
                "R": wordnet.ADV}
    return tag_dict.get(tag, wordnet.NOUN)

# Function to preprocess the documents
def preprocess_text(text):
    # Tokenization
    tokens = word_tokenize(text)
    # Remove punctuation and convert to lowercase
    tokens = [token.lower() for token in tokens if token.isalpha()]
    # Remove stopwords
    stop_words = set(stopwords.words('english'))
    tokens = [token for token in tokens if token not in stop_words]

    # Lemmatization
    lemmatizer = WordNetLemmatizer()
    pos_tags = nltk.pos_tag(tokens)
    tokens = [lemmatizer.lemmatize(token, get_wordnet_pos(pos_tag)) for token, pos_tag in pos_tags]

    # Stemming (You can choose to use either stemming or lemmatization. If you want both, you can uncomment the following lines)
    stemmer = PorterStemmer()
    tokens = [stemmer.stem(token) for token in tokens]

    # Join tokens into a single string
    preprocessed_text = ' '.join(tokens)
    return preprocessed_text


# Function to extract text from a PDF file
def extract_text_from_pdf(file_path):
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ''
            for page in reader.pages:
                text += page.extract_text()
            return text
    except Exception as e:
        print(f"Error extracting text from {file_path}: {str(e)}")
        return ''


def build_tfidf_index(directory_path):
    # Get all PDF file paths in the directory
    file_paths = glob.glob(os.path.join(directory_path, '*.pdf'))

    # Initialize the progress bar
    progress_bar = tqdm(total=len(file_paths), desc='Building Index')

    # Preprocess and extract text from PDFs
    preprocessed_texts = []
    for file_path in file_paths:
        text = preprocess_text(extract_text_from_pdf(file_path))
        preprocessed_texts.append(text)
        progress_bar.set_postfix(file=os.path.basename(file_path))
        progress_bar.update(1)

    # Close the progress bar
    progress_bar.close()

    # Initialize the TF-IDF vectorizer
    vectorizer = TfidfVectorizer()
    # Fit the vectorizer with the preprocessed texts
    tfidf_matrix = vectorizer.fit_transform(preprocessed_texts)

    # Get document titles
    document_titles = [os.path.basename(file_path) for file_path in file_paths]

    # Create a dictionary to store the index data
    index_data = {
        'tfidf_matrix': tfidf_matrix,
        'vectorizer': vectorizer,
        'file_paths': file_paths,
        'document_titles': document_titles,
    }

    return index_data


def query_tfidf_index(query, index_data, top_k=5):
    tfidf_matrix = index_data['tfidf_matrix']
    vectorizer = index_data['vectorizer']
    file_paths = index_data['file_paths']
    document_titles = index_data['document_titles']
    print(f"TF-IDF matrix shape: {tfidf_matrix.shape}")
    print(f"Vectorizer vocabulary size: {len(vectorizer.vocabulary_)}")
    print(f"Number of file paths: {len(file_paths)}")
    print(f"Number of document titles: {len(document_titles)}")

    # Preprocess the query and expand it with synonyms
    preprocessed_query = preprocess_text(query)

    # Transform the query into a TF-IDF vector
    query_vector = vectorizer.transform([preprocessed_query])
    # Calculate the cosine similarities between the query and documents
    similarities = (tfidf_matrix * query_vector.T).toarray().flatten()
    # Get the top-k most similar documents
    top_indices = similarities.argsort()[:-top_k - 1:-1]

    relevance_scores = similarities[top_indices]
    top_paths = [file_paths[index] for index in top_indices]
    top_titles = [document_titles[index] for index in top_indices]

    return relevance_scores, top_paths, top_titles

def build_tfidf_index_with_lsi(directory_path):
    # Get all PDF file paths in the directory
    file_paths = glob.glob(os.path.join(directory_path, '*.pdf'))

    # Initialize the progress bar
    progress_bar = tqdm(total=len(file_paths), desc='Building Index')

    # Preprocess and extract text from PDFs
    preprocessed_texts = []
    for file_path in file_paths:
        text = preprocess_text(extract_text_from_pdf(file_path))
        preprocessed_texts.append(text)
        progress_bar.set_postfix(file=os.path.basename(file_path))
        progress_bar.update(1)

    # Close the progress bar
    progress_bar.close()

    # Initialize the TF-IDF vectorizer
    vectorizer = TfidfVectorizer()
    # Fit the vectorizer with the preprocessed texts
    tfidf_matrix = vectorizer.fit_transform(preprocessed_texts)

    # Get document titles
    document_titles = [os.path.basename(file_path) for file_path in file_paths]

    # Apply LSI using Truncated SVD
    lsi_model = TruncatedSVD(n_components=num_topics)
    lsi_matrix = lsi_model.fit_transform(tfidf_matrix)


    # Create a dictionary to store the index data
    index_data = {
        'tfidf_matrix': tfidf_matrix,
        'vectorizer': vectorizer,
        'file_paths': file_paths,
        'document_titles': document_titles,
        'lsi_matrix': lsi_matrix,
        'lsi_model': lsi_model

    }

    return index_data


# Function to save data as pickle
def save_as_pickle(data, file_path):
    try:
        with open(file_path, 'wb') as file:
            pickle.dump(data, file)
        print(f"Data saved as pickle: {file_path}")
    except Exception as e:
        print(f"Error saving data as pickle: {str(e)}")


# Function to load data from pickle
def load_from_pickle(file_path):
    try:
        with open(file_path, 'rb') as file:
            data = pickle.load(file)
        print(f"Data loaded from pickle: {file_path}")
        return data
    except Exception as e:
        print(f"Error loading data from pickle: {str(e)}")
        return None

def query_lsi_index(query, index_data, top_k=5):
    lsi_matrix = index_data['lsi_matrix']
    vectorizer = index_data['vectorizer']
    lsi_model = index_data['lsi_model']
    file_paths = index_data['file_paths']
    document_titles = index_data['document_titles']

    # Preprocess the query
    preprocessed_query = preprocess_text(query)
    query_vector = vectorizer.transform([preprocessed_query])

    # Convert the query into LSI space
    lsi_query_vector = lsi_model.transform(query_vector)

    # Calculate cosine similarities in the LSI space
    similarities = cosine_similarity(lsi_matrix, lsi_query_vector).flatten()

    # Get the top-k most similar documents
    top_indices = similarities.argsort()[:-top_k - 1:-1]

    relevance_scores = similarities[top_indices]
    top_paths = [file_paths[index] for index in top_indices]
    top_titles = [document_titles[index] for index in top_indices]

    return relevance_scores, top_paths, top_titles


def main():
    parser = argparse.ArgumentParser(description='PDF Search Engine')
    parser.add_argument('--index', type=str, default='index_data.pkl', help='Path to the index file (default: index_data.pkl)')
    parser.add_argument('--docs', type=str, default='docs', help='Path to the directory containing PDF documents (default: docs)')
    parser.add_argument('--update-index', action='store_true', help='Update the index if it already exists')
    parser.add_argument('--mode', type=str, choices=['tfidf', 'lsi'], default='tfidf',
                        help='Choose between "tfidf" and "lsi" modes (default: tfidf)')

    args = parser.parse_args()

    index_path = args.index
    docs_path = args.docs
    update_index = args.update_index

    if os.path.exists(index_path) and not update_index:
        # Load the existing index data
        index_data = load_from_pickle(index_path)
        if index_data is None:
            print("Error loading the index data. Please make sure the index file exists.")
            return
        print("Index loaded from existing file.")
    else:
        if not os.path.exists(docs_path):
            print(f"Documents directory '{docs_path}' does not exist.")
            return

        # Build the TF-IDF index
        index_data = {}
        if args.mode == 'tfidf':
            index_data = build_tfidf_index(docs_path)
        elif args.mode == 'lsi':
            index_data = build_tfidf_index_with_lsi(docs_path)  # A function that builds the index with LSI

        # Save the TF-IDF matrix and vectorizer
        save_as_pickle(index_data, index_path)

        print("Indexing completed.")

    while True:
        query = input("Enter your query (or 'q' to quit): ")
        if query.lower() == 'q':
            break

        relevance_scores = {}
        top_paths = {}
        top_titles = {}

        if args.mode == 'tfidf':
            relevance_scores, top_paths, top_titles = query_tfidf_index(query, index_data, 5)
        elif args.mode == 'lsi':
            relevance_scores, top_paths, top_titles = query_lsi_index(query, index_data,
                                                                      5)  # A function that queries the LSI index

        print("Top results:")
        for score, path, title in zip(relevance_scores, top_paths, top_titles):
            print("Relevance Score:", score)
            print("Path:", path)
            print("Title:", title)

if __name__ == '__main__':
    main()