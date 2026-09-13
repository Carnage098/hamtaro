from services.archetype_meta_service import ArchetypeMetaService
from services.archetype_web_routes import _is_hidden_archetype


def test_dd_family_is_hidden_from_archetype_pages():
    service = ArchetypeMetaService(database_path=":memory:")

    assert _is_hidden_archetype(service, "D/D")
    assert _is_hidden_archetype(service, "D / D")
    assert _is_hidden_archetype(service, "D/D/D")


def test_other_archetypes_remain_visible():
    service = ArchetypeMetaService(database_path=":memory:")

    assert not _is_hidden_archetype(service, "Blue-Eyes")
    assert not _is_hidden_archetype(service, "P.U.N.K.")
