from eyd.canonical import canonical_bytes, canonical_json, hash_obj, record_hash

VECTOR_OBJ = {"b": 1, "a": "x"}
VECTOR_CANONICAL = '{"a":"x","b":1}'
VECTOR_HASH = "sha256:cdab067e9f3beb32d1252cfd63e492592fecbf591b0d08cadb24bb17f3864246"


def test_vector_canonical_bytes():
    assert canonical_json(VECTOR_OBJ) == VECTOR_CANONICAL
    assert canonical_bytes(VECTOR_OBJ) == VECTOR_CANONICAL.encode("utf-8")


def test_vector_hash():
    assert hash_obj(VECTOR_OBJ) == VECTOR_HASH


def test_canonical_sorted_and_no_whitespace():
    assert canonical_json({"z": {"b": 2, "a": 1}, "a": [1, 2]}) == '{"a":[1,2],"z":{"a":1,"b":2}}'


def test_record_hash_ignores_sig():
    rec = {"a": 1, "sig": "ed25519:zzz"}
    assert record_hash(rec) == hash_obj({"a": 1})
    assert record_hash({"a": 1, "sig": "ed25519:aaa"}) == record_hash(rec)
