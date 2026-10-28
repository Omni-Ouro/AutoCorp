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


# --- RFC 8785 (JCS) conformance ------------------------------------------


def test_jcs_numbers_ecmascript_formatting():
    # RFC 8785 §3.2.2.3 / ECMAScript Number::toString serialization.
    cases = {
        1e20: "100000000000000000000",
        1e21: "1e+21",
        1e30: "1e+30",
        1e-6: "0.000001",
        1e-7: "1e-7",
        4.50: "4.5",
        2e-3: "0.002",
        333333333.33333329: "333333333.3333333",
        1.0: "1",
        -0.0: "0",
        0: "0",
        -42: "-42",
        9007199254740991: "9007199254740991",
    }
    for value, expected in cases.items():
        assert canonical_json(value) == expected, value


def test_jcs_rfc8785_sample_object():
    # The sample in RFC 8785 Appendix B.
    obj = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
        "string": "€$\u000f\nA'B\"\\\"/",
        "literals": [None, True, False],
    }
    assert canonical_json(obj) == (
        '{"literals":[null,true,false],'
        '"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\"/"}'
    )


def test_jcs_key_sorting_is_utf16_order():
    # U+10000 encodes in UTF-16 as D800 DC00, which sorts before U+E000 —
    # the opposite of Unicode code-point order.
    assert canonical_json({"": 1, "\U00010000": 2}) == '{"\U00010000":2,"":1}'


def test_jcs_string_escaping():
    assert canonical_json("a\tb\u0001c") == '"a\\tb\\u0001c"'
    assert canonical_json("back\\slash") == '"back\\\\slash"'
    assert canonical_json("€ raw") == '"€ raw"'  # non-ASCII stays raw UTF-8
