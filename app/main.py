from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import List, Optional
from openai import OpenAI
from pymilvus import MilvusClient
import os
import json
import uvicorn

# OpenAI API Client
openai = OpenAI(api_key="OPENAI_KEY_PLACEHOLDER_2")  # Replace with your actual API key

# Milvus (Zilliz Cloud) Config
MILVUS_URI = "https://in03-5cb306ff5a2a6e3.serverless.gcp-us-west1.cloud.zilliz.com"
MILVUS_TOKEN = "MILVUS_TOKEN_PLACEHOLDER"
client = MilvusClient(uri=MILVUS_URI, token=MILVUS_TOKEN)
COLLECTION_NAME = "company_profiles"

# ✅ Lifecycle Manager for Kafka Consumer
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle function to manage the Kafka consumer.
    """
    yield  # App runs during this phase

# ✅ Use the new FastAPI lifespan structure
app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "FastAPI with Milvus is running!"}

class SearchRequest(BaseModel):
    query: str
    locations: Optional[List[int]] = None
    service_ids: Optional[List[str]] = None

async def extract_fields_from_query(query: str):
    """ Extracts specialties, industries, and technologies_used using GPT with a fixed JSON structure """
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": """You analyze service requests and product demands to intelligently infer relevant business fields.

INSTRUCTIONS:
1. The user will provide a query describing a service need, product requirement, or business request.
2. Your task is to infer what company specialties, industries, and technologies would be most relevant to fulfilling this request.
3. Think broadly - consider both explicit mentions and implicit requirements.
4. Be specific and precise in your identifications.

For example, if the query is "I need a website for my restaurant":
- Expertises might include: "web development", "UI/UX design", "restaurant technology"
- Technologies might include: "responsive design", "content management systems", "online ordering systems"

Return ONLY valid JSON in this exact format:
{
    "expertise": ["expertise1", "expertise2", ...],
    "technologies_used": ["tech1", "tech2", ...],
}"""
            },
            {"role": "user", "content": query}
        ]
    )

    try:
        extracted_data = json.loads(response.choices[0].message.content)  # Ensure valid JSON
        return extracted_data
    except json.JSONDecodeError:
        # Fallback with error logging
        print(f"ERROR: Failed to parse JSON from model response: {response.choices[0].message.content}")
        return {"expertise": [], "technologies_used": []}  # Fallback in case of an error

async def get_text_embedding(text_list):
    """ Converts a list of texts into embeddings and returns a list of vectors """
    text = " ".join(text_list) if text_list else ""
    response = openai.embeddings.create(input=text, model="text-embedding-ada-002")
    return response.data[0].embedding if response.data else [0.0] * 1536  # Fallback zero-vector

@app.post("/search")
async def search_companies(request: SearchRequest):
    query = request.query  
    locations = request.locations
    service_ids = request.service_ids
    
    # Log the received filters
    print(f"Searching with filters - Locations: {locations}, Service IDs: {service_ids}")
    
    extracted_fields = await extract_fields_from_query(query)

    # Get embeddings for the extracted fields
    expertise_embedding = await get_text_embedding(extracted_fields.get("expertise", []))
    technologies_embedding = await get_text_embedding(extracted_fields.get("technologies_used", []))
    
    search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}, "top_k": 100}
    """
    def build_filter_expr():
        expr = []
        
        # Add location filter if provided
        if locations and len(locations) > 0:
            location_expr = f'location in [{",".join(str(loc) for loc in locations)}]'
            expr.append(location_expr)
        
        #  Add service_ids filter using ARRAY_CONTAINS_ANY if provided
        if service_ids and len(service_ids) > 0:
            # Format the list of service IDs as a string representation of an array
            service_ids_str = "[" + ",".join([f'"{sid}"' for sid in service_ids]) + "]"
            service_expr = f'ARRAY_CONTAINS_ANY(services, {service_ids_str})'
            expr.append(service_expr)
        
        # Combine expressions with 'and' if both are present
        if expr:
            return " and ".join(expr)
        return None
    
    filter_expr = build_filter_expr()
    print(f"Using filter expression: {filter_expr}")
    if filter_expr:
        search_params["expr"] = filter_expr

    print(f"Using filter expression: {filter_expr}")
    print(f"Search params: {search_params}")
    """
    def run_search(embedding, anns_field):
        return client.search(
            collection_name=COLLECTION_NAME,
            data=[embedding],
            anns_field=anns_field,
            search_params=search_params,
            output_fields=["id", "name", "location", "services"],
        )[0]  # Get first result set since we search one vector at a time

    # Run searches for the two vector fields we have
    results_expertise = run_search(expertise_embedding, "specialties")  # Note: stored as "specialties" in Milvus
    results_technologies = run_search(technologies_embedding, "technologies_used")

    print(f"Expertise Results: {results_expertise}")
    print(f"Technologies Results: {results_technologies}")

    def apply_filters(results):
        filtered = []
        for item in results:
            # Check if the item has the entity field
            if 'entity' not in item:
                continue
                
            # Check location filter
            location_match = True
            if locations and len(locations) > 0:
                # Location is inside the entity object
                if 'location' not in item['entity'] or item['entity']['location'] not in locations:
                    location_match = False
            
            # Check services filter
            services_match = True
            if service_ids and len(service_ids) > 0:
                # Services is inside the entity object
                if 'services' not in item['entity'] or not any(sid in item['entity']['services'] for sid in service_ids):
                    services_match = False
            
            # Only include if both filters match
            if location_match and services_match:
                filtered.append(item)
        
        return filtered

    # After your existing filtered results code:

    # After your existing filtered results code:

    # First get your filtered results as you already do
    filtered_expertise = apply_filters(results_expertise)
    filtered_technologies = apply_filters(results_technologies)

    # Process filtered results as you already do
    all_results = filtered_expertise + filtered_technologies
    merged = {}
    for item in all_results:
        company_id = item["id"]
        similarity = item["distance"]
        if company_id in merged:
            merged[company_id]["Distance"] += similarity
        else:
            merged[company_id] = {"CompanyId": company_id, "Distance": similarity, "MatchesFilters": True}

    # Sort filtered results as you already do
    ranked = sorted(merged.values(), key=lambda x: x["Distance"], reverse=True)

    # Debug: Print the filtered results
    print("BEFORE EXTEND - Filtered results:", len(ranked))
    if ranked:
        print("Sample filtered result:", ranked[0])

    # Get IDs of companies that are already in the ranked list
    ranked_ids = set(item["CompanyId"] for item in ranked)

    # Process unfiltered results
    unfiltered_results = []
    for item in results_expertise + results_technologies:
        company_id = item["id"]
        # Only process if not already in ranked list
        if company_id not in ranked_ids:
            unfiltered_results.append({
                "CompanyId": company_id,
                "Distance": item["distance"],
                "MatchesFilters": False
            })
            # Make sure we don't add duplicates
            ranked_ids.add(company_id)

    # Sort unfiltered results
    unfiltered_results.sort(key=lambda x: x["Distance"], reverse=True)

    # Debug: Print the unfiltered results
    print("Unfiltered results to be added:", len(unfiltered_results))
    if unfiltered_results:
        print("Sample unfiltered result:", unfiltered_results[0])

    # Simply append unfiltered to filtered
    ranked.extend(unfiltered_results)

    # Debug: Print the combined results
    print("AFTER EXTEND - Combined results:", len(ranked))
    if ranked:
        print("First filtered result:", ranked[0])
        if len(ranked) > len(merged):
            print("First unfiltered result:", ranked[len(merged)])

    return {
        "query": query,
        "extracted": extracted_fields,
        "filters": {
            "locations": locations,
            "service_ids": service_ids 
        },
        "results": ranked
    }