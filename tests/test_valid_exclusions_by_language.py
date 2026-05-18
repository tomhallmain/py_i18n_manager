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

    def test_single_locale_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["es"], "Bien")

    def test_empty_locale_list_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster([], "Bien")

    def test_empty_text_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["es", "fr"], "")
        assert not is_allowed_cross_locale_identical_cluster(["es", "fr"], "   ")

    def test_duplicate_base_language_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["es", "es-ES"], "Bien")

    def test_allowed_value_wrong_language_pair_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["de", "fr"], "Bien")
        assert not is_allowed_cross_locale_identical_cluster(["es", "it"], "Profil")
        assert not is_allowed_cross_locale_identical_cluster(["es", "fr"], "Compartir")

    def test_extra_locale_outside_group_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["de", "fr", "es"], "Profil")

    def test_unknown_value_for_valid_pair_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["es", "it"], "Hola")
