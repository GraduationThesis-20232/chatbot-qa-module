import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import pickle
import json
from text_untils import *
import torch
import pymongo
from bson import ObjectId
from pymongo import MongoClient

# df = pd.read_json('data/cleaned/temp.json', lines=True)
top_20_indices_title = []
top_20_indices_anwser = []
doc_scores = []
top_docs = []
ids_title = []
similarities_title = []
sentences_title = []
sentences_anwser = []
ids_anwser = []
similarities_anwser = []

def create_answer(row):
    conclusion_value = row['conclusion']

    if isinstance(conclusion_value, list):
        conclusion_value = ' '.join(conclusion_value)
    elif pd.isna(conclusion_value):
        conclusion_value = ''

    if pd.isna(row['quote']):
        return conclusion_value
    else:
        reference = row['reference'] if not pd.isna(row['reference']) else ''
        merged_quote = merge_quote(row['quote'])
        return f"{reference} {merged_quote}"

def merge_quote(quote):
    if isinstance(quote, dict):
        name = quote.get('name', ' ')
        content = ' '.join(quote.get('content', []))

        if name is None:
            name = ' '
        if content is None:
            content = ' '

        return f"{name}. {content}"
    else:
        return None

def get_selected_rows_from_mongodb(database_name, collection_name, top_docs):
    client = MongoClient('mongodb://localhost:27017/')
    db = client[database_name]
    collection = db[collection_name]

    doc_ids = [ObjectId(doc_dict['id']) for doc_dict in top_docs]

    cursor = collection.find({'_id': {'$in': doc_ids}})
    data = list(cursor)
    df = pd.DataFrame(data)

    # client.close()
    return df

def preprocess(query):
    query = clean_text(query)
    query = word_segment(query)
    query = remove_stopword(normalize_text(query))
    return query
def load_docs_from_file(file_path):
    docs = []
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            try:
                doc = json.loads(line)
                docs.append(doc)
            except json.JSONDecodeError:
                continue

    return docs

def handle_bm25(query):
    query_bm25 = preprocess(query)
    query_bm25 = query_bm25.split()

    with open('output/bm25/bm25plus.pkl', 'rb') as f:
        bm25plus = pickle.load(f)

    docs = load_docs_from_file('output/bm25/docs.jsonl')

    global top_docs
    top_docs = bm25plus.get_top_n(query_bm25, [doc for doc in docs], n=50)
    bm25_scores = bm25plus.get_scores(query_bm25)
    global doc_scores
    doc_scores = np.sort(bm25_scores)[::-1][:50]
    # for doc_dict, score in zip(top_docs, doc_scores):
    #     doc_id = doc_dict['id']
    #     doc_title = doc_dict['title']
    #     print(f"ID: {doc_id}, Document: {doc_title}, Score: {score}")

    # doc_ids = [doc_dict['id'] for doc_dict in top_docs]
    # selected_rows = df[df['_id'].isin(doc_ids)]
    selected_rows = get_selected_rows_from_mongodb('lawlaboratory', 'questions_cleaned', top_docs)

    return selected_rows

def handle_sbert_title(query, selected_rows):
    global sentences_title
    global ids_title

    for idx in selected_rows.index:
        sentences_title.append(selected_rows.at[idx, 'title'])
        ids_title.append(selected_rows.at[idx, '_id'])

    model_title = SentenceTransformer('keepitreal/vietnamese-sbert', device='cuda')
    embeddings_title = model_title.encode(sentences_title)

    query_sbert = preprocess(query)
    query_sbert = query_sbert.replace('_', ' ')
    query_embedding_title = model_title.encode([query_sbert], convert_to_tensor=True)
    query_embedding_title = query_embedding_title.cpu().numpy()
    global similarities_title
    similarities_title = cosine_similarity(query_embedding_title, embeddings_title)
    global top_20_indices_title
    top_20_indices_title = np.argsort(similarities_title[0])[::-1][:20]

    # for idx in top_50_indices_title:
    #     similarity_score = similarities_title[0][idx]
    #     similar_sentence = sentences_title[idx]
    #     doc_id = ids_title[idx]
    #     print(f"ID: {doc_id}, Similarity Score: {similarity_score:.4f}, Sentence: {similar_sentence}")

def handle_sbert_answer(query, selected_rows):
    global sentences_anwser
    global ids_anwser

    selected_rows['conclusion'] = selected_rows.apply(lambda row: merge_quote(row['quote']) if row['conclusion'] == [] else row['conclusion'], axis=1)
    selected_rows['answer'] = selected_rows.apply(create_answer, axis=1)

    for idx in selected_rows.index:
        sentences_anwser.append(selected_rows.at[idx, 'answer'])
        ids_anwser.append(selected_rows.at[idx, '_id'])

    query_sbert = preprocess(query)
    query_sbert = query_sbert.replace('_', ' ')

    model_anwser = SentenceTransformer('keepitreal/vietnamese-sbert', device='cuda')
    embeddings_anwser = model_anwser.encode(sentences_anwser)

    query_embedding_anwser = model_anwser.encode([query_sbert], convert_to_tensor=True)
    query_embedding_anwser = query_embedding_anwser.cpu().numpy()
    global similarities_anwser
    similarities_anwser = cosine_similarity(query_embedding_anwser, embeddings_anwser)
    global top_20_indices_anwser
    top_20_indices_anwser = np.argsort(similarities_anwser[0])[::-1][:20]

    # for idx in top_50_indices_anwser:
    #     similarity_score = similarities_anwser[0][idx]
    #     similar_sentence = sentences_anwser[idx]
    #     doc_id = ids_anwser[idx]
    #     print(f"ID: {doc_id}, Similarity Score: {similarity_score:.4f}, Sentence: {similar_sentence}")

def calculate_score():
    score_title_ids = []
    for idx in top_20_indices_title:
        score_title_ids.append({
            'id': ids_title[idx],
            'score': similarities_title[0][idx]
        })

    score_answer_ids = []
    for idx in top_20_indices_anwser:
        score_answer_ids.append({
            'id': ids_anwser[idx],
            'score': similarities_anwser[0][idx]
        })

    title_scores_by_id = {score_dict['id']: score_dict['score'] for score_dict in score_title_ids}
    answer_scores_by_id = {score_dict['id']: score_dict['score'] for score_dict in score_answer_ids}

    score_sbert_ids = []
    for id in set(title_scores_by_id.keys()).intersection(answer_scores_by_id.keys()):
        final_score = title_scores_by_id[id] * answer_scores_by_id[id]
        score_sbert_ids.append({'id': id, 'score': final_score})

    score_sbert_ids = sorted(score_sbert_ids, key=lambda x: x['score'], reverse=True)
    score_bm25_ids = [{'id': doc_dict['id'], 'score': doc_score} for doc_dict, doc_score in zip(top_docs, doc_scores)]
    final_scores = []
    for score_sbert in score_sbert_ids:
        for score_bm25 in score_bm25_ids:
            score_sbert_id = str(score_sbert['id'])
            if score_sbert_id == score_bm25['id']:
                final_score = score_sbert['score'] * score_bm25['score']
                final_scores.append({'id': score_sbert_id, 'final_score': final_score})
                break

    final_scores = sorted(final_scores, key=lambda x: x['final_score'], reverse=True)

    return pd.DataFrame(final_scores[:5])

def print_answer(doc_id):
    client = pymongo.MongoClient("mongodb://localhost:27017/")

    database = client["lawlaboratory"]
    collection = database["questions_cleaned"]

    document = collection.find_one({"_id": ObjectId(doc_id)})
    print(doc_id)
    if document:
        # print("Title:", document.get('title'))

        if 'field' in document and document['field']:
            print("Lĩnh vực câu hỏi: ", document.get('field'))

        if 'reference' in document and document['reference']:
            print("Điều luật tham khảo: ", document.get('reference'))

        if 'quote' in document:
            quote = document['quote']
            if quote is not None:
                print("Nội dung trích dẫn văn bản pháp luật như sau")
                print(quote.get('name'))

                quote_content = quote.get('content', [])
                for item in quote_content:
                    print(item)

        conclusion = document.get('conclusion', [])
        print("Kết luận:")
        for item in conclusion:
            print(item)

def same_question(df_final):
    client = pymongo.MongoClient("mongodb://localhost:27017/")

    database = client["lawlaboratory"]
    collection = database["questions_cleaned"]

    print("Các câu hỏi tương tự")
    for index, row in df_final.iterrows():
        doc_id_str = str(row['id'])
        document = collection.find_one({"_id": ObjectId(doc_id_str)})
        if document:
            title = document.get('title')
            print(f"Câu hỏi: {title}")

if __name__ == '__main__':
    query = input("Câu hỏi: ")

    selected_rows = handle_bm25(query)

    handle_sbert_title(query, selected_rows)
    handle_sbert_answer(query, selected_rows)

    df_final = calculate_score()

    doc_id_value = df_final.iloc[0]['id']
    print_answer(doc_id_value)
    same_question(df_final)