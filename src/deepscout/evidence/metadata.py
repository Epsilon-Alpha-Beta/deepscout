"""可复用的 Evidence 来源类型确定性分类。"""

from urllib.parse import urlsplit

_STANDARDS = {"datatracker.ietf.org", "w3.org"}
_ACADEMIC = {"arxiv.org"}
_GOVERNMENT = {"nist.gov"}
_REPOSITORIES = {"github.com"}
_OFFICIAL_DOCS = {
    "docs.langchain.com",
    "modelcontextprotocol.io",
    "opentelemetry.io",
    "prometheus.io",
    "redis.io",
    "postgresql.org",
    "kubernetes.io",
    "grpc.io",
    "ai.google.dev",
    "platform.openai.com",
    "docs.anthropic.com",
    "docs.crewai.com",
    "microsoft.github.io",
    "genai.owasp.org",
}
_VENDOR_ENGINEERING = {
    "aws.amazon.com",
    "cloud.google.com",
    "elastic.co",
    "qdrant.tech",
    "rabbitmq.com",
    "learn.microsoft.com",
}


def classify_source_url(url: str) -> str:
    host = urlsplit(url).netloc.lower().split(":")[0]
    if host in _STANDARDS:
        return "standards"
    if host in _ACADEMIC:
        return "academic"
    if host in _GOVERNMENT or host.endswith(".gov"):
        return "government"
    if host in _REPOSITORIES:
        return "source_repository"
    if host in _OFFICIAL_DOCS:
        return "official_docs"
    if host in _VENDOR_ENGINEERING:
        return "vendor_engineering"
    return "secondary"
