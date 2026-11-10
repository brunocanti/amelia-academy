# Amelia Academy JSON contracts

Files in `json-schema/` use JSON Schema Draft 2020-12 and stable IDs under `https://schemas.amelia.academy/v1/`. They are contracts between the control plane, workers, and bounded contexts. The IDs are identifiers; they do not require network access.

## Compatibility

- `schema_version` is required and constant for each published major/minor.
- Optional additive changes require a new contract minor and tolerant consumers when the envelope allows it.
- Removing/renaming a field, changing a type, making an optional field required, or changing semantics requires a new major `$id` (`/v2/`).
- Stable objects use `additionalProperties: false`; extensions must be proposed in the schema, not sent informally.
- UUIDs and ULIDs are accepted in ID fields; hashes are lowercase hexadecimal SHA-256.
- Manifests must be canonically serialized by the application before hashing; JSON Schema validates structure, not canonicalization or cross-record invariants.
- Additional semantic compatibility — same `project_id`, monotonic sequence, split leakage prevention, and current consent — belongs to the domain.

## Validation

The script first reads every JSON file with the standard library, then validates schemas and fixtures:

```sh
python3 scripts/validate-contracts.py
```

If `jsonschema` is not installed, the script confirms JSON syntax, prints the install instruction, and exits with code `2`:

```sh
python3 -m pip install 'jsonschema>=4.18'
```

Fixtures in `fixtures/valid/` must pass; same-named fixtures in `fixtures/invalid/` must fail. The six covered core contracts are `job-request`, `job-event`, `canonical-sample`, `dataset-manifest`, `model-spec`, and `model-release`.

## Safe use

Validating a payload does not grant authorization, verify artifact existence, or replace project gates, consent, hash, or state checks. Resolvers must map `$id` values to approved local copies and must not fetch arbitrary schemas from the network.

## Proposed direct/reasoned extension

ADR 019 and spec 016 describe a future version, not supported by the current contracts. `canonical-sample` v1 continues to carry the final conversation; approved editorial rationales require a separate versioned artifact. `model-spec` v1 only accepts `assistant_final_only`; reasoned training needs a versioned contract with a distinct loss policy and fixtures. Do not silently accept reasoning fields through the v1 envelopes.

## Neutral editorial export implemented

`training-manifest.schema.json` v2 and `editorial-rationale.schema.json` v1 describe the new neutral export artifacts. The training manifest records `identity_sha256`, `split_policy`, `split_warnings` and, per file, `by_kind`. They coexist with the existing dataset manifest and canonical samples; published v1 contracts are not extended in place. The training manifest requires `reasoned_renderer: null` until model-specific rendering is verified. No reasoned model-spec or training support is claimed yet.
