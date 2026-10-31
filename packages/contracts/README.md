# Contracts

`openapi.json` is generated from the FastAPI app and is the contract the web client's types are
checked against. It is committed to the repository, and CI fails if it is out of date.

```
python scripts/export_openapi.py          # regenerate after changing a route or response model
python scripts/export_openapi.py --check  # what CI runs; exits non-zero when the file is stale
```

Commit the regenerated file together with the route change that caused it.
