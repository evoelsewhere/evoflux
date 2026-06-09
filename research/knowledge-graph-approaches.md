# Comprehensive Comparison: Knowledge Graph Extraction from Documents using LLMs

## Executive Summary

This document analyzes how 7 major open-source projects extract knowledge graphs from documents using LLMs, with specific focus on prompts, pipelines, deduplication strategies, and storage approaches. Each section includes extractable code patterns suitable for a local-first SQLite-based system.

---

## 1. Microsoft GraphRAG (github.com/microsoft/graphrag)

### Pipeline Overview
```
Documents → Chunking → Entity/Relation Extraction → Entity Summarization → 
Community Detection (Leiden) → Community Report Generation → Dual-Level Retrieval
```

### Entity Extraction Approach

GraphRAG uses a **structured tuple format** for entity/relation extraction. The LLM outputs entities and relations as delimited records:

**Entity Types Guidance** (configurable YAML profile):
```
- Person: Human individuals, real or fictional
- Creature: Non-human living beings
- Organization: Companies, institutions, government bodies
- Location: Geographic places
- Event: Occurrences, incidents, ceremonies
- Concept: Abstract ideas, theories, principles
- Method: Procedures, techniques, algorithms
- Content: Creative or informational works
- Data: Quantitative or structured information
- Artifact: Physical or digital objects
- NaturalObject: Natural non-living objects
```

**System Prompt** (from `lightrag/prompt.py`, which ports GraphRAG's approach):
```
---Role---
You are a Knowledge Graph Specialist responsible for extracting entities and relationships.

---Instructions---
1. Entity Extraction:
  - entity_name: Capitalize first letter of each significant word (title case)
  - entity_type: Categorize using provided type guidance
  - entity_description: Concise yet comprehensive description

2. Relationship Extraction:
  - source_entity / target_entity: Consistent naming
  - relationship_keywords: High-level keywords separated by comma
  - relationship_description: Concise explanation

3. Output Format:
  - Entity: entity<|>entity_name<|>entity_type<|>entity_description
  - Relation: relation<|>source<|>target<|>keywords<|>description

4. Output Order: All entities first, then all relationships
5. At most {max_total_records} total rows, {max_entity_records} entity rows
```

**User Prompt**:
```
---Input Text---
```
{input_text}
```
---Output---
```

### JSON Mode (Higher Quality)

GraphRAG v3+ supports JSON output for more stable extraction:
```json
{
  "entities": [
    {"name": "...", "type": "...", "description": "..."}
  ],
  "relationships": [
    {"source": "...", "target": "...", "keywords": "...", "description": "..."}
  ]
}
```

### Gleaning (Multi-Pass Extraction)

GraphRAG performs **multiple extraction passes** on the same chunk to catch missed entities:
```
MANY entities were missed in the last extraction. Add them below using the same format:
```
Then checks: `It appears some entities may have still been missed. Answer YES | NO if there are still entities that need to be added.`

### Document Chunking

GraphRAG supports multiple strategies:
- **Token-based**: Split by token count with overlap
- **Recursive**: Hierarchical splitting by separators
- **Paragraph**: Split on paragraph boundaries
- **Vector-based**: Semantic similarity-based splitting

Default chunk size: ~600 tokens with ~100 token overlap.

### Entity Deduplication & Summarization

When the same entity appears across multiple chunks, GraphRAG **merges descriptions** using a map-reduce approach:

**Summarization Prompt**:
```
---Role---
You are a Knowledge Graph Specialist, proficient in data curation and synthesis.

---Task---
Synthesize a list of descriptions of a given entity or relation into a single, 
comprehensive, and cohesive summary.

---Instructions---
1. Integrate all key information from *every* provided description
2. Written from objective, third-person perspective
3. Explicitly mention the full name at the beginning
4. Handle conflicting descriptions by determining if they refer to distinct entities
5. Length must not exceed {summary_length} tokens
```

**Map-Reduce Strategy**:
1. If total tokens < threshold and descriptions < force_llm_summary_on_merge → join directly
2. If total tokens < summary_max_tokens → single LLM call
3. Otherwise → split into chunks, summarize each, recurse

### Community Detection + Hierarchical Summarization

This is GraphRAG's **key differentiator**:

1. **Leiden Algorithm**: Runs community detection on the knowledge graph
2. **Hierarchical Levels**: Creates multiple levels of community hierarchy
3. **Community Reports**: Generates structured reports for each community

**Community Report Prompt**:
```
Write a comprehensive report of a community, given a list of entities 
that belong to the community as well as their relationships.

Report Structure:
- TITLE: community's name representing key entities
- SUMMARY: Executive summary of community structure
- IMPACT SEVERITY RATING: float score 0-10
- RATING EXPLANATION: Single sentence explanation
- DETAILED FINDINGS: 5-10 key insights, each with summary + explanation

Output as JSON:
{
  "title": "...",
  "summary": "...",
  "rating": 5.0,
  "rating_explanation": "...",
  "findings": [
    {"summary": "...", "explanation": "..."}
  ]
}
```

### Storage (Parquet/SQLite in practice)

```
entities:    id, name, type, description, source_id, file_path, timestamp
relations:   id, source, target, description, keywords, weight, source_id
communities: id, level, title, summary, rating, findings (JSON)
text_chunks: id, content, source_id, file_path
```

### What Makes It Better

1. **Community-level summaries** capture global themes that chunk-level extraction misses
2. **Hierarchical structure** enables both high-level overview and detailed drill-down
3. **Gleaning** catches entities missed in first pass
4. **Map-reduce summarization** handles entity descriptions across hundreds of chunks

---

## 2. LightRAG (github.com/HKUDS/LightRAG)

### Pipeline Overview
```
Documents → Chunking → Entity/Relation Extraction → Description Merging →
Graph Storage + Vector Storage → Dual-Level Retrieval (Local + Global)
```

### Entity Extraction Approach

LightRAG uses nearly identical prompts to GraphRAG but adds **relationship_keywords** and a more robust JSON mode.

**Default Entity Types**:
```
- Person, Creature, Organization, Location, Event
- Concept, Method, Content, Data, Artifact, NaturalObject
```

**Text-Mode Extraction Format**:
```
entity<|#|>entity_name<|#|>entity_type<|#|>entity_description
relation<|#|>source_entity<|#|>target_entity<|#|>relationship_keywords<|#|>relationship_description
```

**JSON-Mode Extraction** (recommended, `ENTITY_EXTRACTION_USE_JSON=true`):
```json
{
  "entities": [
    {"name": "Entity Name", "type": "Person", "description": "..."}
  ],
  "relationships": [
    {"source": "A", "target": "B", "keywords": "works_at,employs", "description": "..."}
  ]
}
```

### Key Differences from GraphRAG

1. **No community detection** - avoids expensive Leiden algorithm
2. **Dual-level retrieval** instead of hierarchical communities
3. **Incremental updates** - new documents merge into existing graph without rebuilding
4. **Much cheaper** - fewer LLM calls during both indexing and querying

### Dual-Level Retrieval

**Local Mode**: Retrieves specific entities and their direct relationships
- Good for: "What is X?" or specific factual queries

**Global Mode**: Retrieves broad relationship chains and themes
- Good for: "What are the main themes?" or cross-document queries

**Hybrid Mode**: Combines both local and global results

**Mix Mode** (default): Combines local + global + naive (chunk-level) retrieval

**Keyword Extraction Prompt**:
```
---Role---
You are an expert keyword extractor for a RAG system.

---Goal---
Extract two types of keywords:
1. high_level_keywords: overarching concepts or themes
2. low_level_keywords: specific entities, proper nouns, technical jargon

Output: {"high_level_keywords": [...], "low_level_keywords": [...]}
```

### Description Merging

Same map-reduce approach as GraphRAG but with configurable:
- `FORCE_LLM_SUMMARY_ON_MERGE`: Min descriptions before LLM summarization
- `MAX_SOURCE_IDS_PER_RELATION`: Max chunks per entity/relation
- `SOURCE_IDS_LIMIT_METHOD`: FIFO or keep-latest when limit exceeded

### Storage Architecture

LightRAG uses **4 storage backends**:

1. **KV_STORAGE**: LLM cache, chunks, entity/relation data
2. **VECTOR_STORAGE**: Embeddings for chunks, entities, relations
3. **GRAPH_STORAGE**: Knowledge graph (NetworkX, Neo4j, etc.)
4. **DOC_STATUS_STORAGE**: Document tracking for incremental updates

Default: JSON files. Production: PostgreSQL, MongoDB, or specialized (Milvus + Neo4j).

### What Makes It Better

1. **Dual-level retrieval** without expensive community detection
2. **Incremental updates** - no full rebuild on new documents
3. **Much cheaper** - ~10x fewer LLM calls than GraphRAG
4. **Supports local models** (Ollama, etc.) with JSON mode for stability

---

## 3. nano-graphrag (github.com/gusye1234/nano-graphrag)

### Pipeline Overview
```
Documents → Chunking → Entity/Relation Extraction → Entity Summarization →
Community Detection → Community Reports → Global/Local Search
```

### Entity Extraction Prompt

Directly adapted from Microsoft GraphRAG:

```
-Goal-
Given a text document and a list of entity types, identify all entities 
of those types from the text and all relationships among them.

-Steps-
1. Identify all entities. For each:
   - entity_name: Name, capitalized
   - entity_type: One of [{entity_types}]
   - entity_description: Comprehensive description
   Format: ("entity"<SEP>entity_name<SEP>entity_type<SEP>entity_description)

2. Identify all pairs of (source_entity, target_entity) that are *clearly related*:
   - source_entity, target_entity
   - relationship_description: why they are related
   - relationship_strength: numeric score
   Format: ("relationship"<SEP>source<SEP>target<SEP>description<SEP>strength)

3. Return as single list with record delimiter
4. Output completion delimiter when finished
```

**Default Entity Types**: `["organization", "person", "geo", "event"]`

**Delimiters**:
- Tuple: `<|>`
- Record: `##`
- Completion: `<|COMPLETE|>`

### Community Report Prompt

Same structure as GraphRAG:
```
Write a comprehensive report of a community given entities and relationships.

Return as JSON:
{
  "title": "...",
  "summary": "...",
  "rating": 0-10,
  "rating_explanation": "...",
  "findings": [{"summary": "...", "explanation": "..."}]
}
```

### Global Search (Map-Reduce)

nano-graphrag simplifies GraphRAG's global search:
- **Original GraphRAG**: Map-reduce across ALL communities
- **nano-graphrag**: Only uses top-K most important/central communities (default: 512)

**Map Prompt**: Extract key points with importance scores from each community
**Reduce Prompt**: Synthesize analyst reports ranked by importance

### Key Simplifications vs GraphRAG

1. **~1100 lines of code** vs GraphRAG's massive codebase
2. **Top-K communities** instead of full map-reduce
3. **No covariates** feature
4. **NetworkX** default graph storage (vs Parquet files)
5. **Fully async** and typed

### Storage

```python
# Three storage abstractions:
BaseKVStorage      → JSON file (default), any KV store
BaseVectorStorage  → nano-vectordb (default), hnswlib, milvus-lite, faiss
BaseGraphStorage   → NetworkX (default), Neo4j
```

### Chunking

```python
# Token-based (default)
chunking_by_token_size(text, max_token_size, overlap_token_size)

# Text splitter based
chunking_by_seperators(text, separators=["\n\n", "\n", "。", ".", " "])
```

---

## 4. LlamaIndex Knowledge Graph

### Pipeline Overview (Property Graph - Recommended)

```
Documents → Chunks → SimpleLLMPathExtractor / ImplicitPathExtractor →
Property Graph Store → Hybrid Retrieval (Keyword + Embedding + NL2GraphQuery)
```

### Entity Extraction: SimpleLLMPathExtractor

LlamaIndex uses a **simpler triplet extraction** approach:

**Default Prompt** (`DEFAULT_KG_TRIPLET_EXTRACT_PROMPT`):
```
Extract knowledge graph triples from the text below.
Each triple should be in the form: (subject, predicate, object)

---------------------
{text}
---------------------

Provide up to {max_knowledge_triplets} triples.
Format: (subject, predicate, object) separated by newlines.
```

**Parsing**: Simple regex-based extraction of `(subject, predicate, object)` tuples.

### Older Approach: KnowledgeGraphIndex

The deprecated but instructive approach:

1. **Keyword Extraction**: LLM extracts keywords from each chunk
2. **Entity Mapping**: Keywords map to graph nodes
3. **Rel Map**: `graph_store.get_rel_map(entities, depth=2)` for subgraph retrieval

**Query Keyword Extraction**:
```
Extract {max_keywords} keywords from the question below.
Question: {question}
KEYWORDS:
```

**Synonym Expansion**:
```
Generate synonyms or possible forms of keywords up to {max_keywords},
considering capitalization, pluralization, common expressions.
Provide all synonyms in comma-separated format: 'SYNONYMS: <keywords>'
KEYWORDS: {question}
```

### Retrieval Modes

1. **Keyword**: Extract keywords from query → find matching triplets
2. **Embedding**: Semantic similarity to stored triplets
3. **Hybrid**: Both keyword and embedding combined
4. **NL2GraphQuery**: Convert natural language to graph query language

### What Makes It Different

1. **Simplest approach** - just extract (subject, predicate, object) triples
2. **No community detection** or hierarchical summarization
3. **Graph-native retrieval** using graph traversal (`get_rel_map` with depth)
4. **Synonym expansion** for better entity matching
5. **Property Graph Index** (newer) supports custom extraction pipelines

---

## 5. Mem0 (github.com/mem0ai/mem0)

### Pipeline Overview
```
Messages → Fact Extraction (LLM) → Memory Deduplication →
Entity Linking (spaCy) → Vector Storage → Multi-Signal Retrieval
```

### V3 Memory Extraction (ADD-Only)

Mem0's newest approach uses **single-pass ADD-only extraction**:

**Extraction Prompt** (abbreviated):
```
# ROLE
You are a Memory Extractor — a precise, evidence-bound processor 
responsible for extracting rich, contextual memories from conversations.

# INPUTS
- New Messages: Current conversation
- Summary: User profile from prior conversations
- Recently Extracted: Deduplication reference (up to 20)
- Existing Memories: For deduplication and linking

# GUIDELINES
- Extract ALL memorable information from both user and assistant messages
- Contextually rich, not atomic (15-80 words per memory)
- Self-contained (replace pronouns with names)
- Temporally grounded (convert relative → absolute dates)
- Preserve specific details — never generalize

# EXAMPLES
Input: "Hey! I'm Marcus. I just got promoted to Senior Engineer at Shopify..."
Output: {"memory": [
  {"id": "0", "text": "User's name is Marcus and was promoted to Senior Engineer at Shopify around August 12, 2025"},
  {"id": "1", "text": "Marcus has a wife named Elena and they celebrate special occasions at Osteria Francescana"}
]}
```

### Entity Extraction (NLP-based, not LLM)

Mem0 uses **spaCy** for entity extraction (no LLM calls):

```python
def extract_entities(text: str) -> List[Tuple[str, str]]:
    # Four extraction methods:
    # 1. PROPER: Capitalized multi-word sequences
    # 2. QUOTED: Text in quotes
    # 3. COMPOUND: Noun compounds with modifiers
    # 4. NOUN: Single nouns from compound patterns
    
    # Returns: [(entity_type, entity_text), ...]
```

**Deduplication**:
- Normalize to lowercase
- Priority: PROPER > COMPOUND > QUOTED > NOUN
- Remove entities that are substrings of longer entities
- Generic word filtering (e.g., "thing", "stuff", "work")

### Entity Linking

```python
def _upsert_entity(entity_text, entity_type, memory_id, filters):
    # 1. Embed entity text
    # 2. Search for existing entity (threshold: 0.95)
    # 3. If found: add memory_id to linked_memory_ids
    # 4. If not found: create new entity record
```

### Multi-Signal Retrieval (V3)

```
Semantic (embedding) + BM25 (keyword) + Entity matching → Score fusion
```

### Storage

```
Vector Store (Qdrant/FAISS):
  - Memory records: {data, hash, created_at, updated_at, user_id, ...}
  - Entity records: {data, entity_type, linked_memory_ids, user_id, ...}

SQLite:
  - Message history per session
  - Memory event log (ADD/UPDATE/DELETE)
```

### What Makes It Different

1. **Conversational memory** - extracts from chat, not documents
2. **spaCy entity extraction** - no LLM cost for entity extraction
3. **Memory linking** - entities connect related memories
4. **Temporal reasoning** - resolves relative dates
5. **Single-pass ADD** - no UPDATE/DELETE operations (V3)

---

## 6. Khoj (github.com/khoj-ai/khoj)

### Approach

Khoj is primarily a **search and chat application** rather than a knowledge graph builder:

- **Document Indexing**: PDFs, Markdown, Org-mode, Word, Notion
- **Search**: Semantic search using embeddings
- **Chat**: RAG over indexed documents with web search integration
- **No knowledge graph extraction** - uses traditional chunk-level retrieval

### Key Takeaway

Khoj demonstrates that for many use cases, **good semantic search + chunking** is sufficient without building a knowledge graph.

---

## 7. Anytype (github.com/anyproto/anytype-ts)

### Approach

Anytype is a **local-first knowledge OS** with:

- **Object-based model**: Everything is an object with types and relations
- **Graph structure**: Objects link to each other via relations
- **No LLM extraction** - users manually create objects and links
- **gRPC API** for programmatic access
- **End-to-end encrypted** sync

### Key Takeaway

Anytype's object graph model is worth studying for the **data model** design, even though it doesn't use LLM extraction.

---

## Comparison Matrix

| Feature | GraphRAG | LightRAG | nano-graphrag | LlamaIndex | Mem0 |
|---------|----------|----------|---------------|------------|------|
| **Entity Extraction** | LLM (tuple/JSON) | LLM (tuple/JSON) | LLM (tuple) | LLM (triplets) | spaCy NLP |
| **Relationship Extraction** | LLM | LLM | LLM | LLM | Implicit |
| **Chunking** | Token/recursive/paragraph/vector | Fix/recursive/vector/paragraph | Token/separator | Various | Message-level |
| **Deduplication** | Name matching + LLM merge | Name matching + LLM merge | Name matching + LLM merge | Name matching | Embedding similarity (0.95) |
| **Summarization** | Map-reduce LLM | Map-reduce LLM | Map-reduce LLM | None | None |
| **Community Detection** | Leiden algorithm | None | Leiden algorithm | None | None |
| **Wiki Pages** | Community reports | None | Community reports | None | None |
| **Incremental Updates** | Full rebuild | Merge-based | Full rebuild | Additive | Always incremental |
| **Retrieval** | Community → local/global | Local/global/hybrid/mix | Local/global | Keyword/embedding/hybrid | Semantic + BM25 + entity |
| **LLM Calls (indexing)** | Very high | Medium | Very high | Low | Low (spaCy) |
| **Storage** | Parquet/SQLite | KV/Vector/Graph/Doc | JSON/nano-vectordb/NetworkX | Graph store + docstore | Vector store + SQLite |

---

## Recommended Architecture for Local-First SQLite System

Based on this analysis, here's a recommended hybrid approach:

### Phase 1: Document Ingestion
```
Documents → Chunking (token-based with overlap) → Store in SQLite
```

### Phase 2: Knowledge Extraction
```
For each chunk:
  1. Extract entities + relations using LLM (GraphRAG-style JSON prompt)
  2. Optional: gleaning pass to catch missed entities
  3. Store in SQLite: entities, relations, chunk_entity_map
```

### Phase 3: Entity Deduplication & Merging
```
For each unique entity name:
  1. Collect all descriptions from different chunks
  2. If descriptions < threshold: concatenate
  3. If descriptions >= threshold: LLM summarize (map-reduce)
  4. Store merged description
```

### Phase 4: Community Detection (Optional)
```
1. Build NetworkX graph from SQLite relations
2. Run Leiden community detection
3. Generate community reports using LLM
4. Store in SQLite: communities table
```

### Phase 5: Wiki Page Generation
```
For each community:
  1. Gather entities, relations, chunk references
  2. Generate structured wiki page using LLM
  3. Store as browsable markdown in SQLite
```

### SQLite Schema

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    file_path TEXT,
    content_hash TEXT,
    created_at TIMESTAMP
);

CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES documents(id),
    content TEXT,
    chunk_index INTEGER,
    token_count INTEGER,
    heading_path TEXT
);

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE,
    entity_type TEXT,
    description TEXT,
    source_chunk_ids TEXT,  -- JSON array
    embedding BLOB,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE relations (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT REFERENCES entities(id),
    target_entity_id TEXT REFERENCES entities(id),
    keywords TEXT,
    description TEXT,
    weight REAL,
    source_chunk_ids TEXT,  -- JSON array
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE communities (
    id TEXT PRIMARY KEY,
    level INTEGER,
    title TEXT,
    summary TEXT,
    rating REAL,
    rating_explanation TEXT,
    findings TEXT,  -- JSON array
    entity_ids TEXT,  -- JSON array
    wiki_content TEXT  -- Generated markdown
);

CREATE TABLE llm_cache (
    id TEXT PRIMARY KEY,
    prompt_hash TEXT,
    response TEXT,
    model TEXT,
    created_at TIMESTAMP
);

CREATE TABLE document_status (
    document_id TEXT PRIMARY KEY,
    status TEXT,  -- 'pending', 'processing', 'completed', 'failed'
    processed_at TIMESTAMP
);
```

### Prompt Templates (Adapted for Local Use)

**Entity Extraction (JSON mode)**:
```python
ENTITY_EXTRACTION_PROMPT = """Extract entities and relationships from the text.

Entity types: {entity_types}

Output JSON:
{{
  "entities": [
    {{"name": "...", "type": "...", "description": "..."}}
  ],
  "relationships": [
    {{"source": "...", "target": "...", "keywords": "...", "description": "..."}}
  ]
}}

Rules:
- Max {max_entities} entities, {max_relations} relationships
- Names: Title Case, consistent across extractions
- Descriptions: concise, third-person, based only on the text
- Relationships: undirected, no duplicates

Text:
```
{input_text}
```
"""
```

**Entity Summary (Map-Reduce)**:
```python
ENTITY_SUMMARY_PROMPT = """Synthesize these descriptions into one comprehensive summary.

Entity: {entity_name}
Descriptions:
{description_list}

Rules:
- Include ALL key information from every description
- Third person, mention entity name at beginning
- Resolve contradictions
- Max {max_tokens} tokens
"""
```

**Community Report**:
```python
COMMUNITY_REPORT_PROMPT = """Write a report for this community of related entities.

Entities: {entities_csv}
Relations: {relations_csv}

Output JSON:
{{
  "title": "...",
  "summary": "...",
  "rating": 0.0-10.0,
  "rating_explanation": "...",
  "findings": [
    {{"summary": "...", "explanation": "..."}}
  ]
}}
"""
```

**Wiki Page Generation**:
```python
WIKI_PAGE_PROMPT = """Generate a wiki page for this topic based on the knowledge graph data.

Topic: {community_title}
Entities: {entities}
Relations: {relations}
Source excerpts: {excerpts}

Generate a comprehensive wiki page in markdown with:
1. Overview section
2. Key entities and their descriptions
3. Relationships and connections
4. Source references

Format: Markdown
"""
```

### LLM Provider Flexibility

```python
async def complete(prompt: str, system_prompt: str = None, **kwargs) -> str:
    """Works with any provider: OpenAI, Anthropic, Ollama, local models."""
    provider = os.getenv("LLM_PROVIDER", "ollama")
    
    if provider == "openai":
        # OpenAI API
    elif provider == "anthropic":
        # Anthropic API
    elif provider == "ollama":
        # Ollama local
    else:
        # Generic OpenAI-compatible API
```

---

## Key Insights for Implementation

### 1. Start Simple (LlamaIndex approach)
- Extract (subject, predicate, object) triples
- Good enough for most use cases
- Low LLM cost

### 2. Add Description Enrichment (GraphRAG/LightRAG approach)
- Rich entity descriptions improve retrieval quality
- Map-reduce summarization for cross-chunk entities

### 3. Add Community Detection (GraphRAG approach)
- Only if you need "global overview" queries
- Leiden algorithm is fast, community report generation is expensive
- Skip if most queries are specific/factual

### 4. Dual-Level Retrieval (LightRAG approach)
- Local: entity-centric retrieval for specific queries
- Global: relationship-chain retrieval for thematic queries
- Hybrid: combine both

### 5. Deduplication Strategy
- **Name normalization**: Title case, strip whitespace
- **Semantic dedup**: Embedding similarity threshold (0.95)
- **Description merge**: LLM-based or concatenation

### 6. Caching is Critical
- Cache all LLM responses by prompt hash
- Enables incremental updates without re-extraction
- LightRAG and nano-graphrag both do this

### 7. For Code + Docs Mixed Content
- Use **section context** (heading breadcrumbs) during extraction
- Code entities: functions, classes, modules, variables
- Doc entities: concepts, features, APIs
- Relations: imports, calls, extends, implements, documents
