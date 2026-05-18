from i18n.valid_exclusions_by_language import is_allowed_cross_locale_identical_cluster


class TestCrossLanguageSharedIdenticalValues:
    def test_es_fr_bien_allowed(self):
        assert is_allowed_cross_locale_identical_cluster(["es", "fr"], "Bien")

    def test_de_fr_profil_allowed(self):
        assert is_allowed_cross_locale_identical_cluster(["de", "fr"], "Profil")

    def test_es_it_compartir_allowed(self):
        assert is_allowed_cross_locale_identical_cluster(["es", "it"], "Compartir")

    def test_unrelated_cluster_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["de", "fr"], "Bonjour")

    def test_subset_locales_must_match_group(self):
        assert is_allowed_cross_locale_identical_cluster(["es-ES", "fr-FR"], "bien")
