"""Skill taxonomy: canonical names, aliases and categories, used for both resumes and job descriptions.

Extraction is deterministic so a score can be reproduced and explained. Ambiguous words are matched
case-sensitively or only in unambiguous forms ("React" or "react.js", never "react to incidents";
"Golang" or "Go" capitalised, never "go live").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Skill:
    name: str
    category: str  # language | backend | frontend | ai | cloud | devops | data | testing | practice
    aliases: tuple[str, ...] = ()
    case_sensitive: tuple[str, ...] = ()  # aliases that only count with this exact casing


_SKILLS: tuple[Skill, ...] = (
    # languages
    Skill("Java", "language", ("java", "core java", "java 8", "java 11", "java 17", "java 21", "j2ee", "jakarta ee")),
    Skill("Python", "language", ("python", "python3", "python 3")),
    Skill("TypeScript", "language", ("typescript",)),
    Skill("JavaScript", "language", ("javascript", "ecmascript", "es6")),
    Skill("SQL", "language", ("sql",)),
    # A bare "Go" starts too many sentences ("Go beyond ...") to count as the language.
    Skill("Go", "language", ("golang", "go lang", "go programming")),
    Skill("Kotlin", "language", ("kotlin",)),
    Skill("C++", "language", ("c++", "cpp")),
    Skill("C#", "language", ("c#", "c sharp")),
    Skill(".NET", "backend", (".net", "asp.net", "dotnet")),
    Skill("Rust", "language", ("rust",), ()),
    Skill("Scala", "language", ("scala",)),
    # backend
    Skill("Spring Boot", "backend", ("spring boot", "springboot")),
    Skill("Spring Framework", "backend", ("spring framework", "spring mvc", "spring")),
    Skill("Spring Security", "backend", ("spring security",)),
    Skill("Hibernate", "backend", ("hibernate", "hibernate orm")),
    Skill("JPA", "backend", ("jpa", "spring data jpa")),
    Skill("REST APIs", "backend", ("rest api", "rest apis", "restful", "rest services", "restful apis")),
    Skill("Microservices", "backend", ("microservices", "microservice", "micro-services")),
    Skill("Kafka", "backend", ("kafka", "apache kafka")),
    Skill("RabbitMQ", "backend", ("rabbitmq",)),
    Skill("Event-Driven Architecture", "backend", ("event-driven", "event driven")),
    Skill("GraphQL", "backend", ("graphql",)),
    Skill("gRPC", "backend", ("grpc",)),
    Skill("WebSockets", "backend", ("websocket", "websockets")),
    Skill("FastAPI", "backend", ("fastapi",)),
    Skill("Django", "backend", ("django",)),
    Skill("Flask", "backend", ("flask",)),
    Skill("Node.js", "backend", ("node.js", "nodejs", "node js")),
    Skill("Express", "backend", ("express.js", "expressjs")),
    Skill("Distributed Systems", "backend", ("distributed systems", "distributed system")),
    Skill("System Design", "practice", ("system design", "systems design")),
    Skill("OAuth2", "backend", ("oauth2", "oauth 2", "oauth")),
    Skill("JWT", "backend", ("jwt",)),
    Skill("Maven", "devops", ("maven",)),
    Skill("Gradle", "devops", ("gradle",)),
    # frontend
    Skill("React", "frontend", ("react.js", "reactjs", "react 18", "react js"), ("React",)),
    Skill("Redux", "frontend", ("redux",)),
    Skill("Next.js", "frontend", ("next.js", "nextjs")),
    Skill("Angular", "frontend", ("angular",)),
    Skill("Vue.js", "frontend", ("vue.js", "vuejs"), ("Vue",)),
    Skill("HTML", "frontend", ("html", "html5")),
    Skill("CSS", "frontend", ("css", "css3")),
    Skill("Tailwind CSS", "frontend", ("tailwind",)),
    Skill("Material UI", "frontend", ("material ui", "material-ui", "mui")),
    # AI
    Skill("LLMs", "ai", ("llm", "llms", "large language model", "large language models")),
    Skill("Generative AI", "ai", ("generative ai", "genai", "gen ai")),
    Skill("RAG", "ai", ("rag", "retrieval-augmented generation", "retrieval augmented generation")),
    Skill("Vector Search", "ai", ("vector search", "vector database", "vector databases", "vector db", "vector store")),
    Skill("Embeddings", "ai", ("embeddings", "embedding models", "vertex ai embeddings")),
    Skill("AI Agents", "ai", ("ai agents", "ai agent", "agentic", "autonomous agents", "multi-agent")),
    Skill("Google ADK", "ai", ("google adk", "agent development kit", "adk")),
    Skill("Vertex AI", "ai", ("vertex ai", "vertex ai reasoning engine", "reasoning engine", "agent engine")),
    Skill("Gemini", "ai", ("gemini",)),
    Skill("OpenAI", "ai", ("openai", "gpt-4", "gpt-4o", "gpt-5", "chatgpt")),
    Skill("Azure OpenAI", "ai", ("azure openai",)),
    Skill("Prompt Engineering", "ai", ("prompt engineering", "prompt design")),
    Skill("MCP", "ai", ("mcp", "model context protocol", "mcp servers")),
    Skill("A2A", "ai", ("a2a", "agent-to-agent", "agent to agent")),
    Skill("LLM Orchestration", "ai", ("llm orchestration", "model orchestration", "multi-llm")),
    Skill("Tool Calling", "ai", ("tool calling", "function calling", "tool use")),
    Skill("LangChain", "ai", ("langchain",)),
    Skill("LangGraph", "ai", ("langgraph",)),
    Skill("LlamaIndex", "ai", ("llamaindex", "llama index")),
    Skill("Fine-tuning", "ai", ("fine-tuning", "fine tuning", "finetuning")),
    Skill("Machine Learning", "ai", ("machine learning",), ("ML",)),
    Skill("NLP", "ai", ("nlp", "natural language processing")),
    Skill("PyTorch", "ai", ("pytorch",)),
    Skill("TensorFlow", "ai", ("tensorflow",)),
    Skill("Hugging Face", "ai", ("hugging face", "huggingface", "transformers library")),
    Skill("MLOps", "ai", ("mlops", "llmops")),
    # data stores
    Skill("MySQL", "data", ("mysql",)),
    Skill("PostgreSQL", "data", ("postgresql", "postgres")),
    Skill("MongoDB", "data", ("mongodb", "mongo db")),
    Skill("Redis", "data", ("redis",)),
    Skill("DynamoDB", "data", ("dynamodb",)),
    Skill("Elasticsearch", "data", ("elasticsearch", "opensearch")),
    Skill("Cassandra", "data", ("cassandra",)),
    Skill("pgvector", "data", ("pgvector",)),
    Skill("Pinecone", "data", ("pinecone",)),
    Skill("BigQuery", "data", ("bigquery",)),
    Skill("Spark", "data", ("apache spark", "pyspark"), ("Spark",)),
    Skill("Airflow", "data", ("airflow",)),
    # cloud & devops
    Skill("AWS", "cloud", ("aws", "amazon web services", "ec2", "s3", "aws lambda")),
    Skill("GCP", "cloud", ("gcp", "google cloud", "google cloud platform", "cloud run", "cloud storage")),
    Skill("Azure", "cloud", ("azure", "microsoft azure", "azure key vault")),
    Skill("Serverless", "cloud", ("serverless", "lambda functions", "cloud functions")),
    Skill("Docker", "devops", ("docker", "containerization", "containerisation", "containerized", "containerised")),
    Skill("Kubernetes", "devops", ("kubernetes", "k8s", "gke", "eks", "aks")),
    Skill("Terraform", "devops", ("terraform",)),
    Skill("CI/CD", "devops", ("ci/cd", "ci cd", "continuous integration", "continuous delivery", "continuous deployment")),
    Skill("GitLab CI", "devops", ("gitlab ci", "gitlab ci/cd", "gitlab")),
    Skill("GitHub Actions", "devops", ("github actions",)),
    Skill("Jenkins", "devops", ("jenkins",)),
    Skill("SonarQube", "devops", ("sonarqube",)),
    Skill("Linux", "devops", ("linux", "unix")),
    Skill("Git", "devops", ("git",), ()),
    Skill("Observability", "devops", ("observability", "prometheus", "grafana", "opentelemetry")),
    # testing & practice
    Skill("JUnit", "testing", ("junit", "junit 5", "junit5")),
    Skill("Mockito", "testing", ("mockito",)),
    Skill("TDD", "testing", ("tdd", "test-driven", "test driven")),
    Skill("Integration Testing", "testing", ("integration testing", "integration tests")),
    Skill("API Testing", "testing", ("api testing", "postman")),
    Skill("Pytest", "testing", ("pytest",)),
    Skill("Design Patterns", "practice", ("design patterns", "design pattern")),
    Skill("SOLID", "practice", ("solid principles",), ("SOLID",)),
    Skill("OOP", "practice", ("oop", "object-oriented", "object oriented")),
    Skill("Data Structures & Algorithms", "practice", ("data structures", "algorithms", "dsa")),
    Skill("Agile", "practice", ("agile", "scrum")),
)

# Domain signals for the "AI, cloud, architecture or domain" criterion; matched in addition to the
# ai/cloud categories above.
DOMAIN_TERMS: tuple[str, ...] = (
    "automation",
    "hyperautomation",
    "workflow",
    "orchestration",
    "enterprise",
    "platform",
    "saas",
    "scalable",
    "scalability",
    "high availability",
    "low latency",
    "integrations",
    "connectors",
    "rpa",
    "developer tools",
    "devtools",
    "b2b",
    "fintech",
    "product company",
)

ROLE_FAMILIES: dict[str, dict[str, object]] = {
    "ai_engineering": {
        "label": "AI / Agent Engineering",
        "title_words": ("ai", "ml", "genai", "llm", "agent", "agentic", "machine learning", "applied", "generative"),
        "categories": ("ai",),
    },
    "full_stack": {
        "label": "Full Stack",
        "title_words": ("full stack", "fullstack", "full-stack", "frontend", "front end", "ui"),
        "categories": ("frontend", "backend"),
    },
    "java_backend": {
        "label": "Java Backend",
        "title_words": ("backend", "back end", "back-end", "java", "server", "platform", "api", "sde", "software"),
        "categories": ("backend", "data", "cloud"),
    },
}


def _alias_pattern(alias: str) -> str:
    escaped = re.escape(alias).replace(r"\ ", r"[\s\-]?")
    # Word boundaries that also work for aliases ending in symbols (c++, c#, .net, ci/cd).
    return rf"(?<![\w.+#]){escaped}(?![\w+#]|\.\w)"


@lru_cache
def _compiled() -> tuple[tuple[Skill, re.Pattern[str] | None, re.Pattern[str] | None], ...]:
    out = []
    for skill in _SKILLS:
        insensitive = [a for a in skill.aliases if a not in skill.case_sensitive]
        ci = re.compile("|".join(_alias_pattern(a) for a in insensitive), re.IGNORECASE) if insensitive else None
        cs = re.compile("|".join(_alias_pattern(a) for a in skill.case_sensitive)) if skill.case_sensitive else None
        out.append((skill, ci, cs))
    return tuple(out)


_BY_NAME = {s.name.lower(): s for s in _SKILLS}


def get_skill(name: str) -> Skill | None:
    return _BY_NAME.get(name.lower())


def category_of(name: str) -> str | None:
    skill = get_skill(name)
    return skill.category if skill else None


def extract_skills(text: str) -> list[str]:
    """Canonical skill names found in ``text``, in taxonomy order, without duplicates."""
    found: list[str] = []
    for skill, ci, cs in _compiled():
        if (ci and ci.search(text)) or (cs and cs.search(text)):
            found.append(skill.name)
    if "Spring Boot" in found and "Spring Framework" in found:
        # "Spring Boot" alone must not also count as the Spring Framework (one fact, two skills).
        rest = re.sub(r"spring[\s-]?boot", " ", text, flags=re.IGNORECASE)
        _, ci, _ = next(c for c in _compiled() if c[0].name == "Spring Framework")
        if not (ci and ci.search(rest)):
            found.remove("Spring Framework")
    return found


def canonicalize(name: str) -> str:
    """Map a free-form skill name (from the user or an LLM) to the taxonomy, or keep it as written."""
    hits = extract_skills(name)
    return hits[0] if len(hits) == 1 else name.strip()


def extract_domain_terms(text: str) -> list[str]:
    lowered = text.lower()
    return [t for t in DOMAIN_TERMS if re.search(rf"\b{re.escape(t)}\b", lowered)]


def all_skill_names() -> list[str]:
    return [s.name for s in _SKILLS]
