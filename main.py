import os
from typing import List, Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI(title="Job Finder API", version="1.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Job(BaseModel):
    id: str
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    salary: Optional[str] = None
    url: str
    source: str
    tags: Optional[List[str]] = None
    description: Optional[str] = None


@app.get("/")
def read_root():
    return {"message": "Job Finder Backend Running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        from database import db
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


@app.get("/api/jobs", response_model=List[Job])
def search_jobs(
    query: Optional[str] = Query(None, description="Search keywords"),
    location: Optional[str] = Query(None, description="City, country (not all providers support)"),
    category: Optional[str] = Query(None, description="Provider category (e.g., software-dev)"),
    job_type: Optional[str] = Query(None, description="full_time, part_time, contract, internship"),
    remote: Optional[bool] = Query(None, description="Remote only"),
    limit: int = Query(50, ge=1, le=200)
):
    """
    Aggregate jobs from public sources and normalize shape.
    Currently uses Remotive public API which includes direct job URLs.
    """
    jobs: List[Job] = []

    # Remotive API
    try:
        remotive_params = {}
        if query:
            remotive_params["search"] = query
        if category:
            remotive_params["category"] = category
        if job_type:
            remotive_params["job_type"] = job_type
        # Remotive is remote-first. If remote is explicitly False, we'll still return results.

        r = requests.get("https://remotive.com/api/remote-jobs", params=remotive_params, timeout=10)
        if r.ok:
            data = r.json()
            for item in data.get("jobs", []):
                # Basic normalization
                job = Job(
                    id=str(item.get("id")),
                    title=item.get("title") or "Untitled",
                    company=item.get("company_name"),
                    location=item.get("candidate_required_location"),
                    type=item.get("job_type"),
                    salary=item.get("salary"),
                    url=item.get("url"),
                    source="Remotive",
                    tags=item.get("tags"),
                    description=item.get("description")
                )

                # Location filtering (best-effort, case-insensitive substring match)
                if location:
                    loc_src = (job.location or "").lower()
                    if location.lower() not in loc_src:
                        # allow common remote-anywhere synonyms if user typed "remote" or similar
                        user_loc = location.lower().strip()
                        remote_synonyms = {"remote", "anywhere", "worldwide", "global"}
                        if not (user_loc in remote_synonyms and any(s in loc_src for s in remote_synonyms)):
                            continue

                # Remote filter (best-effort)
                if remote is True:
                    loc_src = (job.location or "").lower()
                    if not any(s in loc_src for s in ["remote", "anywhere", "worldwide", "global"]):
                        continue
                # if remote is False, we keep as-is (Remotive skews remote already)

                jobs.append(job)
    except Exception:
        # Silently continue with what we have
        pass

    # Optionally: add a fallback link to Google Jobs search when no provider used
    if not jobs and (query or location):
        # Provide synthetic entries linking to Google, Indeed, LinkedIn searches
        q = " ".join([p for p in [query, location] if p])
        providers = [
            ("Google Jobs", f"https://www.google.com/search?q={q.replace(' ', '+')}+jobs"),
            ("LinkedIn", f"https://www.linkedin.com/jobs/search/?keywords={q.replace(' ', '%20')}") ,
            ("Indeed", f"https://www.indeed.com/jobs?q={q.replace(' ', '+')}")
        ]
        for i, (name, url) in enumerate(providers):
            jobs.append(Job(
                id=f"fallback-{i}",
                title=f"Search '{q}' on {name}",
                company=None,
                location=location,
                type=None,
                salary=None,
                url=url,
                source=name,
                tags=None,
                description=None
            ))

    # Trim to limit regardless of source
    return jobs[:limit]


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
