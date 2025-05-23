from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import List, Optional,Dict,Any
from openai import OpenAI
from pymilvus import MilvusClient
import os
import json
import uvicorn
import dotenv
import asyncio

# Load environment variables from .env file
dotenv.load_dotenv()

# OpenAI API Key
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise ValueError("OPENAI_API_KEY environment variable not set.")

# OpenAI API Client
openai = OpenAI(api_key=openai_api_key)

# Milvus uri and token should be set in the environment variables
milvus_url = os.getenv("MILVUS_URI")
milvus_token = os.getenv("MILVUS_TOKEN")
if not milvus_url or not milvus_token:
    raise ValueError("MILVUS_URL or MILVUS_TOKEN environment variable not set.")

client = MilvusClient(uri=milvus_url, token=milvus_token)
COLLECTION_NAME = "company_profiles"

# Lifecycle Manager for Kafka Consumer
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or your React origin like "http://localhost:3000"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "FastAPI with Milvus is running!"}

# IMPORTANT: Updated this to match frontend data structure
class SearchRequest(BaseModel):
    searchQuery: str
    locations: Optional[List[int]] = None
    serviceIds: Optional[List[str]] = None

class GetFeaturedRequest(BaseModel):
    services: Optional[List[str]] = None
    technologies_used: Optional[List[str]] = None

async def extract_fields_from_query(query: str):
    response = openai.chat.completions.create(
        model="gpt-4.1-nano",
        messages=[
            {"role": "system", "content": """You analyze service requests and product demands to intelligently infer relevant business fields.

INSTRUCTIONS:
1. The user will provide a query describing a service need, product requirement, or business request.
2. Your task is to infer what company specialties, industries, and technologies would be most relevant to fulfilling this request.
3. Think broadly - consider both explicit mentions and implicit requirements.
4. Be specific and precise in your identifications.

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
        extracted_data = json.loads(response.choices[0].message.content)
        return extracted_data
    except json.JSONDecodeError:
        print(f"ERROR: Failed to parse JSON from model response: {response.choices[0].message.content}")
        return {"expertise": [], "technologies_used": []}

async def get_text_embedding(text_list):
    text = " ".join(text_list) if text_list else ""
    response = openai.embeddings.create(input=text, model="text-embedding-ada-002")
    return response.data[0].embedding if response.data else [0.0] * 1536


# @app.post("/get_featured_companies")
# async def get_featured_companies(request: GetFeaturedRequest):
#     # Use the field names from the updated Pydantic model
#     services = request.services
#     technologies_used = request.technologies_used
    
#     print(f"Getting featured companies with filters - Services: {services}, Technologies Used: {technologies_used}")
    
#     extracted_fields = await extract_fields_from_query(" ".join(services + technologies_used))

#     expertise_embedding = await get_text_embedding(extracted_fields.get("expertise", []))
#     technologies_embedding = await get_text_embedding(extracted_fields.get("technologies_used", []))

#     search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}, "top_k": 100}
    
#     def run_search(embedding, anns_field):
#         return client.search(
#             collection_name=COLLECTION_NAME,
#             data=[embedding],
#             anns_field=anns_field,
#             search_params=search_params,
#             output_fields=["id", "company_name", "location", "services", "location_name", "service_names"],
#         )[0]

#     results_expertise = run_search(expertise_embedding, "specialties")
#     results_technologies = run_search(technologies_embedding, "technologies_used")

#     all_results = results_expertise + results_technologies

#     # Create a safely serializable response
#     response = {
#         "query": str(request),
#         "extracted": {
#             "expertise": [str(e) for e in extracted_fields.get("expertise", [])],
#             "technologies_used": [str(t) for t in extracted_fields.get("technologies_used", [])]
#         },
#         "results": all_results
#     }

#     # Return the safely serialized response
#     return response    

# @app.post("/get_featured_companies")
# async def get_featured_companies(request: GetFeaturedRequest):
#     # Use the field names from the updated Pydantic model
#     services = request.services or []  # Handle None case
#     technologies_used = request.technologies_used or []  # Handle None case
    
#     print(f"Getting featured companies with filters - Services: {services}, Technologies Used: {technologies_used}")
    
#     # Ensure we have something to join
#     query_text = " ".join([s for s in (services + technologies_used) if s])
#     extracted_fields = await extract_fields_from_query(query_text)

#     expertise_embedding = await get_text_embedding(extracted_fields.get("expertise", []))
#     technologies_embedding = await get_text_embedding(extracted_fields.get("technologies_used", []))

#     search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}, "top_k": 100}
    
#     def run_search(embedding, anns_field):
#         return client.search(
#             collection_name=COLLECTION_NAME,
#             data=[embedding],
#             anns_field=anns_field,
#             search_params=search_params,
#             output_fields=["id", "company_name", "location", "services", "location_name", "service_names"],
#         )[0]

#     results_expertise = run_search(expertise_embedding, "specialties")
#     results_technologies = run_search(technologies_embedding, "technologies_used")

#     # Process results using a dictionary to keep only the highest scoring result for each company
#     company_results = {}

#     for result in results_expertise + results_technologies:
#         company_id = result.get("id")
#         distance = float(result.get("distance", 0))
        
#         # If we haven't seen this company yet, or this result has a higher score
#         if company_id not in company_results or distance > company_results[company_id]["distance"]:
#             serialized_item = {
#                 "id": company_id,
#                 "distance": distance,
#                 "entity": {}
#             }
            
#             # Extract entity data safely
#             if "entity" in result:
#                 entity = result["entity"]
#                 serialized_entity = {}
                
#                 for key in ["id", "company_name", "location", "location_name"]:
#                     if key in entity:
#                         serialized_entity[key] = entity[key]
                
#                 # Handle lists specially
#                 if "services" in entity:
#                     serialized_entity["services"] = [str(s) for s in entity.get("services", [])]
                
#                 if "service_names" in entity:
#                     serialized_entity["service_names"] = [str(s) for s in entity.get("service_names", [])]
                
#                 serialized_item["entity"] = serialized_entity
            
#             company_results[company_id] = serialized_item

#     # Convert dictionary to list
#     serializable_results = list(company_results.values())

#     # Sort results by distance (highest score first)
#     serializable_results.sort(key=lambda x: x["distance"], reverse=True)

#     # Create a safely serializable response
#     response = {
#         "query": {
#             "services": services,
#             "technologies_used": technologies_used
#         },
#         "extracted": {
#             "expertise": [str(e) for e in extracted_fields.get("expertise", [])],
#             "technologies_used": [str(t) for t in extracted_fields.get("technologies_used", [])]
#         },
#         "results": serializable_results
#     }

#     # Return the safely serialized response
#     return response

@app.post("/get_featured_companies")
async def get_featured_companies(request: GetFeaturedRequest):
    # Use the field names from the updated Pydantic model
    services = request.services or []  # Handle None case
    technologies_used = request.technologies_used or []  # Handle None case
    
    print(f"Getting featured companies with filters - Services: {services}, Technologies Used: {technologies_used}")
    
    # Ensure we have something to join
    query_text = " ".join([s for s in (services + technologies_used) if s])
    extracted_fields = await extract_fields_from_query(query_text)

    expertise_embedding = await get_text_embedding(extracted_fields.get("expertise", []))
    technologies_embedding = await get_text_embedding(extracted_fields.get("technologies_used", []))

    search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}, "top_k": 100}
    
    # Change this to an async function for parallel execution
    async def run_search_async(embedding, anns_field):
        return client.search(
            collection_name=COLLECTION_NAME,
            data=[embedding],
            anns_field=anns_field,
            search_params=search_params,
            output_fields=["id", "company_name", "location", "services", "location_name", "service_names"],
        )[0]

    # Run both searches in parallel
    results_expertise, results_technologies = await asyncio.gather(
        run_search_async(expertise_embedding, "specialties"),
        run_search_async(technologies_embedding, "technologies_used")
    )

    # The rest of your code remains exactly the same
    # Process results using a dictionary to keep only the highest scoring result for each company
    company_results = {}

    for result in results_expertise + results_technologies:
        company_id = result.get("id")
        distance = float(result.get("distance", 0))
        
        # If we haven't seen this company yet, or this result has a higher score
        if company_id not in company_results or distance > company_results[company_id]["distance"]:
            serialized_item = {
                "id": company_id,
                "distance": distance,
                "entity": {}
            }
            
            # Extract entity data safely
            if "entity" in result:
                entity = result["entity"]
                serialized_entity = {}
                
                for key in ["id", "company_name", "location", "location_name"]:
                    if key in entity:
                        serialized_entity[key] = entity[key]
                
                # Handle lists specially
                if "services" in entity:
                    serialized_entity["services"] = [str(s) for s in entity.get("services", [])]
                
                if "service_names" in entity:
                    serialized_entity["service_names"] = [str(s) for s in entity.get("service_names", [])]
                
                serialized_item["entity"] = serialized_entity
            
            company_results[company_id] = serialized_item

    # Convert dictionary to list
    serializable_results = list(company_results.values())

    # Sort results by distance (highest score first)
    serializable_results.sort(key=lambda x: x["distance"], reverse=True)

    # Create a safely serializable response
    response = {
        "query": {
            "services": services,
            "technologies_used": technologies_used
        },
        "extracted": {
            "expertise": [str(e) for e in extracted_fields.get("expertise", [])],
            "technologies_used": [str(t) for t in extracted_fields.get("technologies_used", [])]
        },
        "results": serializable_results
    }

    # Return the safely serialized response
    return response

# ## Pydantic model for the batch request
# class CompanyInfo(BaseModel):
#     id: str
#     name: str
#     services: Optional[List[str]] = None
#     technologiesUsed: Optional[List[str]] = None

# class BatchSimilarCompaniesRequest(BaseModel):
#     companies: List[CompanyInfo]

# @app.post("/get_similar_companies_batch")
# async def get_similar_companies_batch(request: BatchSimilarCompaniesRequest):
#     """
#     Process multiple company requests in a single batch to improve performance.
#     """
#     print(f"Processing batch request for {len(request.companies)} companies")
    
#     # Create a dictionary to store results, keyed by company ID
#     batch_results = {}
    
#     # Prepare search parameters once
#     search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}, "top_k": 100}
#     output_fields = ["id", "company_name", "location", "services", "location_name", "service_names"]
    
#     # Process each company sequentially to avoid overwhelming the embedding service
#     for company in request.companies:
#         company_id = company.id
#         batch_results[company_id] = []
        
#         # Extract services and technologies for this company
#         services = company.services or []
#         technologiesUsed = company.technologiesUsed or []
        
#         # Combine into a single query text
#         query_text = " ".join([s for s in (services + technologiesUsed) if s])
#         if not query_text:
#             continue
            
#         # Extract fields from query
#         extracted_fields = await extract_fields_from_query(query_text)
        
#         # Get embeddings for expertise and technologies
#         expertise_terms = extracted_fields.get("expertise", [])
#         tech_terms = extracted_fields.get("technologies_used", [])
        
#         # Process expertise embedding
#         if expertise_terms:
#             expertise_embedding = await get_text_embedding(expertise_terms)
            
#             # Run search for expertise embedding
#             results_expertise = client.search(
#                 collection_name=COLLECTION_NAME,
#                 data=[expertise_embedding],
#                 anns_field="specialties",
#                 search_params=search_params,
#                 output_fields=output_fields,
#             )
            
#             # Process results
#             if results_expertise and len(results_expertise) > 0:
#                 for result in results_expertise[0]:
#                     process_result(batch_results, company_id, result)
        
#         # Process technologies embedding
#         if tech_terms:
#             tech_embedding = await get_text_embedding(tech_terms)
            
#             # Run search for technologies embedding
#             results_technologies = client.search(
#                 collection_name=COLLECTION_NAME,
#                 data=[tech_embedding],
#                 anns_field="technologies_used",
#                 search_params=search_params,
#                 output_fields=output_fields,
#             )
            
#             # Process results
#             if results_technologies and len(results_technologies) > 0:
#                 for result in results_technologies[0]:
#                     process_result(batch_results, company_id, result)
        
#         # Sort results for this company
#         batch_results[company_id].sort(key=lambda x: x["distance"], reverse=True)
    
#     return batch_results

# def process_result(batch_results, company_id, result):
#     """Process a single search result and add it to the batch results."""
#     result_id = result.get("id")
#     distance = float(result.get("distance", 0))
    
#     # Check if this result is already in the batch_results
#     existing_result = next(
#         (r for r in batch_results[company_id] if r["id"] == result_id), 
#         None
#     )
    
#     if existing_result:
#         # Update if new score is higher
#         if distance > existing_result["distance"]:
#             existing_result["distance"] = distance
#     else:
#         # Create a new entry
#         serialized_item = {
#             "id": result_id,
#             "distance": distance,
#             "entity": {}
#         }
        
#         # Extract entity data safely
#         if "entity" in result:
#             entity = result["entity"]
#             serialized_entity = {}
            
#             for key in ["id", "company_name", "location", "location_name"]:
#                 if key in entity:
#                     serialized_entity[key] = entity[key]
            
#             # Handle lists specially
#             if "services" in entity:
#                 serialized_entity["services"] = [str(s) for s in entity.get("services", [])]
            
#             if "service_names" in entity:
#                 serialized_entity["service_names"] = [str(s) for s in entity.get("service_names", [])]
            
#             serialized_item["entity"] = serialized_entity
        
#         # Add to results
#         batch_results[company_id].append(serialized_item)

@app.post("/search")
async def search_companies(request: SearchRequest):
    # Use the field names from the updated Pydantic model
    query = request.searchQuery
    locations = request.locations
    service_ids = request.serviceIds
    
    print(f"Searching with filters - Locations: {locations}, Service IDs: {service_ids}")
    
    extracted_fields = await extract_fields_from_query(query)

    expertise_embedding = await get_text_embedding(extracted_fields.get("expertise", []))
    technologies_embedding = await get_text_embedding(extracted_fields.get("technologies_used", []))
    
    search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}, "top_k": 100}
    
    def build_filter_expr():
        expr = []
        
        if locations and len(locations) > 0:
            location_expr = f'location in [{",".join(str(loc) for loc in locations)}]'
            expr.append(location_expr)
        
        if service_ids and len(service_ids) > 0:
            service_ids_str = "[" + ",".join([f'"{sid}"' for sid in service_ids]) + "]"
            service_expr = f'ARRAY_CONTAINS_ANY(services, {service_ids_str})'
            expr.append(service_expr)
        
        if expr:
            return " and ".join(expr)
        return None
    
    filter_expr = build_filter_expr()
    if filter_expr:
        search_params["expr"] = filter_expr

    print(f"Using filter expression: {filter_expr}")

    def run_search(embedding, anns_field):
        return client.search(
            collection_name=COLLECTION_NAME,
            data=[embedding],
            anns_field=anns_field,
            search_params=search_params,
            output_fields=["id", "company_name", "location", "services", "location_name", "service_names"],
        )[0]

    results_expertise = run_search(expertise_embedding, "specialties")
    results_technologies = run_search(technologies_embedding, "technologies_used")

    def apply_filters(results):
        filtered = []
        for item in results:
            if 'entity' not in item:
                continue
                
            location_match = True
            if locations and len(locations) > 0:
                if 'location' not in item['entity'] or item['entity']['location'] not in locations:
                    location_match = False
            
            services_match = True
            if service_ids and len(service_ids) > 0:
                if 'services' not in item['entity'] or not any(sid in item['entity']['services'] for sid in service_ids):
                    services_match = False
            
            if location_match and services_match:
                filtered.append(item)
        
        return filtered

    filtered_expertise = apply_filters(results_expertise)
    filtered_technologies = apply_filters(results_technologies)

    all_results = filtered_expertise + filtered_technologies
    merged = {}
    
    # For the initial results
    for item in all_results:
        company_id = item["id"]
        similarity = item["distance"]
        if company_id in merged:
            merged[company_id]["Distance"] += similarity
        else:
            company_data = {
                "CompanyId": str(company_id),  # Ensure string
                "Distance": float(similarity),  # Ensure float
                "MatchesFilters": True,
                "Name": "",  # Initialize with empty string
                "Location": "",  # Initialize with empty string
                "Services": []  # Initialize with empty list
            }
            
            # Add company name if available
            if 'entity' in item and 'company_name' in item['entity']:
                # Handle potential None values
                company_name = item['entity'].get('company_name')
                if company_name is not None:
                    company_data["Name"] = str(company_name)
            
            # Add location if available
            if 'entity' in item and 'location_name' in item['entity']:
                # Handle potential None values
                location_name = item['entity'].get('location_name')
                if location_name is not None:
                    company_data["Location"] = str(location_name)
                
            # Process service_names with careful serialization
            if 'entity' in item and 'service_names' in item['entity']:
                service_names = item['entity'].get('service_names')
                if service_names is not None:
                    # Make sure we have a proper list of strings
                    if isinstance(service_names, list):
                        company_data["Services"] = [str(name) for name in service_names if name is not None]
                    else:
                        # Just in case it's a single value
                        company_data["Services"] = [str(service_names)]

            merged[company_id] = company_data

    # Sort by distance
    ranked = sorted(merged.values(), key=lambda x: x["Distance"], reverse=True)

    ranked_ids = set(item["CompanyId"] for item in ranked)

    # Process unfiltered results
    unfiltered_results = []
    for item in results_expertise + results_technologies:
        company_id = item["id"]
        if company_id not in ranked_ids:
            # Use the distance from the current item
            item_distance = float(item["distance"])
            
            company_data = {
                "CompanyId": str(company_id),  # Ensure string
                "Distance": item_distance,  # Use the correct distance for this item
                "MatchesFilters": False,  # This should be False for unfiltered results
                "Name": "",  # Initialize with empty string
                "Location": "",  # Initialize with empty string
                "Services": []  # Initialize with empty list
            }

            # Add company name if available with careful serialization
            if 'entity' in item and 'company_name' in item['entity']:
                company_name = item['entity'].get('company_name')
                if company_name is not None:
                    company_data["Name"] = str(company_name)

            # Add location if available with careful serialization
            if 'entity' in item and 'location_name' in item['entity']:
                location_name = item['entity'].get('location_name')
                if location_name is not None:
                    company_data["Location"] = str(location_name)
                
            # Process service_names with careful serialization
            if 'entity' in item and 'service_names' in item['entity']:
                service_names = item['entity'].get('service_names')
                if service_names is not None:
                    # Make sure we have a proper list of strings
                    if isinstance(service_names, list):
                        company_data["Services"] = [str(name) for name in service_names if name is not None]
                    else:
                        # Just in case it's a single value
                        company_data["Services"] = [str(service_names)]
             
            unfiltered_results.append(company_data)
            ranked_ids.add(company_id)

    # Sort and combine results
    unfiltered_results.sort(key=lambda x: x["Distance"], reverse=True)
    ranked.extend(unfiltered_results)

    # Create a safely serializable response
    response = {
        "query": str(query),
        "extracted": {
            "expertise": [str(e) for e in extracted_fields.get("expertise", [])],
            "technologies_used": [str(t) for t in extracted_fields.get("technologies_used", [])]
        },
        "filters": {
            "locations": [int(loc) if loc is not None else None for loc in locations] if locations else None,
            "service_ids": [str(sid) for sid in service_ids] if service_ids else None
        },
        "results": ranked
    }

    # Return the safely serialized response
    return response

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)