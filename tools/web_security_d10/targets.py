from __future__ import annotations

from pathlib import Path

from tools.web_security_d06.targets import verify_target


HASHES = {
    "A10": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "B11": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "B12": "8e04bcec4e7dd82778858043064dd9676597edade17c496ab16a9042e68bc364",
    "C09": "a8367fed73efce99e93941a6475f386def7dfa25de27b0e2889d4fe00b1ed0d7",
    "F07": "705b8cf34a5315e661de443f27346efa3b97670e81f334f59cb6ab9cd2fff2ee",
}
FILES = {
    "A10": "CDH_A_R08_001_REVIEW.zip",
    "B11": "CDH_B_R07_001_REVIEW.zip",
    "B12": "CDH_B_R08_001_REVIEW.zip",
    "C09": "CDH_C_R08_001_REVIEW.zip",
    "F07": "CDH_F_R08_001_REVIEW.zip",
}
C09_EXTRAS = (
    "CDH_C_R08_001_REVIEW/RELEASE_INFO.json",
    "CDH_C_R08_001_REVIEW/SHA256SUMS.txt",
)


def verify_targets(releases: str | Path) -> dict[str, dict[str, object]]:
    base = Path(releases)
    result: dict[str, dict[str, object]] = {}
    for role, filename in FILES.items():
        identity = verify_target(
            base / filename,
            expected_sha256=HASHES[role],
            reject_undeclared=role != "C09",
        )
        if role == "C09" and identity.manifest_undeclared != C09_EXTRAS:
            raise ValueError(f"C09_PACKAGING_EXCEPTION_MISMATCH:{identity.manifest_undeclared}")
        result[role] = identity.as_dict()
    return result
