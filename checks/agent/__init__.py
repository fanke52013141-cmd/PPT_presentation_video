"""Agent integration test suite.

Tests cover:
1. Capability registry integrity (unique IDs, required fields, model consistency)
2. MCP tool contract alignment (schemas match Pydantic models)
3. CLI command contract alignment
4. Operations normalization
5. Artifact URI building
6. End-to-end API smoke tests (with TestClient)
"""
