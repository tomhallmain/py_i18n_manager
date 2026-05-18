from i18n.valid_exclusions_by_language import (
    is_allowed_cross_locale_identical_cluster,
    is_globally_shared_identical_value,
    EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE,
)


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


class TestGloballySharedIdenticalValues:
    # --- Temperature scales (original entries) ---

    def test_temperature_scales_allowed(self):
        for term in ("celsius", "fahrenheit", "kelvin"):
            assert is_globally_shared_identical_value(term), term

    # --- Universal UI / product conventions ---

    def test_ok_allowed_lowercase(self):
        assert is_globally_shared_identical_value("ok")

    def test_ok_allowed_uppercase(self):
        assert is_globally_shared_identical_value("OK")

    def test_beta_allowed(self):
        assert is_globally_shared_identical_value("beta")
        assert is_globally_shared_identical_value("Beta")

    def test_alpha_allowed(self):
        assert is_globally_shared_identical_value("alpha")

    def test_demo_allowed(self):
        assert is_globally_shared_identical_value("demo")
        assert is_globally_shared_identical_value("Demo")

    def test_wifi_allowed(self):
        assert is_globally_shared_identical_value("wifi")
        assert is_globally_shared_identical_value("WiFi")

    def test_bluetooth_allowed(self):
        assert is_globally_shared_identical_value("bluetooth")
        assert is_globally_shared_identical_value("Bluetooth")

    # --- File / data formats ---

    def test_file_formats_allowed(self):
        for term in ("csv", "html", "json", "pdf", "png", "svg", "xml", "yaml", "yml", "zip"):
            assert is_globally_shared_identical_value(term), term

    def test_file_formats_uppercase_allowed(self):
        for term in ("CSV", "HTML", "JSON", "PDF", "PNG", "SVG", "XML", "YAML", "ZIP"):
            assert is_globally_shared_identical_value(term), term

    # --- SI / digital units ---

    def test_digital_units_allowed(self):
        for term in ("gb", "ghz", "hz", "kb", "kg", "km", "mb", "mhz", "ms", "pb", "px", "tb"):
            assert is_globally_shared_identical_value(term), term

    def test_digital_units_uppercase_allowed(self):
        for term in ("GB", "GHz", "Hz", "KB", "MB", "MHz", "TB", "PB", "PX"):
            assert is_globally_shared_identical_value(term), term

    # --- Network / security protocols ---

    def test_protocols_allowed(self):
        for term in ("ftp", "http", "https", "smtp", "ssh", "ssl", "tcp", "tls", "udp"):
            assert is_globally_shared_identical_value(term), term

    def test_protocols_uppercase_allowed(self):
        for term in ("FTP", "HTTP", "HTTPS", "SMTP", "SSH", "SSL", "TCP", "TLS", "UDP"):
            assert is_globally_shared_identical_value(term), term

    # --- Universal tech identifiers ---

    def test_tech_identifiers_allowed(self):
        for term in ("api", "css", "gps", "sql", "url"):
            assert is_globally_shared_identical_value(term), term

    def test_tech_identifiers_uppercase_allowed(self):
        for term in ("API", "CSS", "GPS", "SQL", "URL"):
            assert is_globally_shared_identical_value(term), term

    # --- Negative cases ---

    def test_common_words_not_globally_shared(self):
        for term in ("hello", "save", "cancel", "settings", "bonjour", "hola"):
            assert not is_globally_shared_identical_value(term), term

    def test_empty_string_not_globally_shared(self):
        assert not is_globally_shared_identical_value("")
        assert not is_globally_shared_identical_value("   ")


class TestEnSharedNewLanguages:
    """Loanword allowlists added for languages not previously covered."""

    # --- Dutch ---

    def test_nl_tech_loanwords_allowed(self):
        nl = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["nl"]
        for term in ("app", "browser", "cache", "chat", "dashboard", "data", "download",
                     "email", "plugin", "server", "software", "upload", "widget"):
            assert term in nl, f"nl missing: {term}"

    def test_nl_unknown_term_not_allowed(self):
        nl = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["nl"]
        assert "bonjour" not in nl
        assert "hola" not in nl

    # --- Scandinavian ---

    def test_sv_tech_loanwords_allowed(self):
        sv = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["sv"]
        for term in ("app", "browser", "cache", "chat", "data", "download",
                     "email", "plugin", "server", "software", "upload"):
            assert term in sv, f"sv missing: {term}"

    def test_no_tech_loanwords_allowed(self):
        no = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["no"]
        for term in ("app", "browser", "cache", "data", "email", "server"):
            assert term in no, f"no missing: {term}"

    def test_da_tech_loanwords_allowed(self):
        da = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["da"]
        for term in ("app", "browser", "cache", "data", "email", "server"):
            assert term in da, f"da missing: {term}"

    # --- Central / Eastern European ---

    def test_pl_tech_loanwords_allowed(self):
        pl = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["pl"]
        for term in ("app", "browser", "cache", "data", "email", "plugin", "server"):
            assert term in pl, f"pl missing: {term}"

    def test_cs_tech_loanwords_allowed(self):
        cs = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["cs"]
        for term in ("app", "browser", "cache", "data", "email", "server"):
            assert term in cs, f"cs missing: {term}"

    def test_sk_tech_loanwords_allowed(self):
        sk = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["sk"]
        for term in ("app", "browser", "cache", "data", "email", "server"):
            assert term in sk, f"sk missing: {term}"

    def test_ro_tech_loanwords_allowed(self):
        ro = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["ro"]
        for term in ("app", "browser", "cache", "data", "email", "server"):
            assert term in ro, f"ro missing: {term}"

    def test_hu_tech_loanwords_allowed(self):
        hu = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["hu"]
        for term in ("app", "browser", "data", "email", "server", "software"):
            assert term in hu, f"hu missing: {term}"

    # --- Turkish ---

    def test_tr_tech_loanwords_allowed(self):
        tr = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["tr"]
        for term in ("app", "browser", "cache", "data", "email", "plugin", "server"):
            assert term in tr, f"tr missing: {term}"

    # --- Indonesian / Malay ---

    def test_id_tech_loanwords_allowed(self):
        id_ = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["id"]
        for term in ("app", "browser", "cache", "data", "email", "server", "software"):
            assert term in id_, f"id missing: {term}"

    def test_ms_tech_loanwords_allowed(self):
        ms = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["ms"]
        for term in ("app", "browser", "cache", "data", "email", "server"):
            assert term in ms, f"ms missing: {term}"

    # --- Greek ---

    def test_el_latin_tech_terms_allowed(self):
        el = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["el"]
        for term in ("api", "email", "html", "http", "https", "json", "pdf", "url", "xml"):
            assert term in el, f"el missing: {term}"

    # --- Cyrillic-script languages (conservative set) ---

    def test_ru_minimal_latin_tech_terms_allowed(self):
        ru = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["ru"]
        for term in ("api", "email", "html", "https", "json", "pdf", "url", "xml"):
            assert term in ru, f"ru missing: {term}"

    def test_uk_minimal_latin_tech_terms_allowed(self):
        uk = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["uk"]
        for term in ("api", "email", "html", "json", "url"):
            assert term in uk, f"uk missing: {term}"

    def test_bg_minimal_latin_tech_terms_allowed(self):
        bg = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["bg"]
        for term in ("api", "email", "json", "url", "xml"):
            assert term in bg, f"bg missing: {term}"

    def test_cyrillic_languages_do_not_contain_full_loanword_sets(self):
        # Cyrillic-script languages only contain minimal protocol/format terms,
        # not the full loanword set that Latin-script languages carry.
        ru = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["ru"]
        assert "browser" not in ru
        assert "dashboard" not in ru
        assert "plugin" not in ru

    # --- Cross-language independence ---

    def test_nl_terms_not_in_ru(self):
        # Dutch-specific loanwords should not bleed into the Cyrillic list.
        nl_only = EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["nl"] - EN_SHARED_IDENTICAL_TERMS_BY_LANGUAGE["ru"]
        assert "browser" in nl_only
        assert "dashboard" in nl_only


class TestCrossLanguageNewGroups:
    """New cross-language groups added in the data expansion."""

    # --- Scandinavian {sv, no, da} ---

    def test_scandinavian_shared_native_cognates(self):
        for term in ("kontakt", "produkt", "profil", "service", "system"):
            assert is_allowed_cross_locale_identical_cluster(["sv", "no", "da"], term), term

    def test_scandinavian_shared_tech_loanwords(self):
        for term in ("browser", "cache", "chat", "data", "download", "email"):
            assert is_allowed_cross_locale_identical_cluster(["sv", "no", "da"], term), term

    def test_scandinavian_subset_pair_sv_no_covered(self):
        assert is_allowed_cross_locale_identical_cluster(["sv", "no"], "kontakt")
        assert is_allowed_cross_locale_identical_cluster(["sv", "no"], "browser")

    def test_scandinavian_subset_pair_sv_da_covered(self):
        assert is_allowed_cross_locale_identical_cluster(["sv", "da"], "service")

    def test_scandinavian_subset_pair_no_da_covered(self):
        assert is_allowed_cross_locale_identical_cluster(["no", "da"], "system")

    def test_scandinavian_unknown_term_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["sv", "no", "da"], "hejsan")

    def test_scandinavian_group_does_not_cover_de(self):
        assert not is_allowed_cross_locale_identical_cluster(["sv", "no", "de"], "browser")

    # --- West Germanic {de, nl} ---

    def test_de_nl_shared_tech_loanwords(self):
        for term in ("app", "browser", "cache", "chat", "data", "download",
                     "email", "plugin", "server", "software", "upload"):
            assert is_allowed_cross_locale_identical_cluster(["de", "nl"], term), term

    def test_de_nl_unknown_term_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["de", "nl"], "Lebkuchen")

    def test_de_nl_does_not_cover_fr(self):
        assert not is_allowed_cross_locale_identical_cluster(["de", "nl", "fr"], "browser")

    # --- Ibero-Romance {es, pt} ---

    def test_es_pt_native_romance_cognates(self):
        for term in ("banco", "canal", "capital", "digital", "global", "grupo",
                     "lista", "local", "manual", "natural", "normal", "nota",
                     "social", "total"):
            assert is_allowed_cross_locale_identical_cluster(["es", "pt"], term), term

    def test_es_pt_shared_tech_loanwords(self):
        for term in ("browser", "cache", "chat", "data", "download", "email"):
            assert is_allowed_cross_locale_identical_cluster(["es", "pt"], term), term

    def test_es_pt_unknown_term_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["es", "pt"], "gracias")

    def test_es_pt_does_not_cover_it(self):
        assert not is_allowed_cross_locale_identical_cluster(["es", "pt", "it"], "digital")

    # --- Central European {pl, cs, sk} ---

    def test_pl_cs_sk_shared_tech_loanwords(self):
        for term in ("app", "browser", "cache", "chat", "data", "download", "email"):
            assert is_allowed_cross_locale_identical_cluster(["pl", "cs", "sk"], term), term

    def test_pl_cs_sk_subset_pair_pl_cs(self):
        assert is_allowed_cross_locale_identical_cluster(["pl", "cs"], "browser")

    def test_pl_cs_sk_subset_pair_cs_sk(self):
        assert is_allowed_cross_locale_identical_cluster(["cs", "sk"], "data")

    def test_pl_cs_sk_unknown_term_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["pl", "cs", "sk"], "dziękuję")

    def test_pl_cs_sk_does_not_cover_de(self):
        assert not is_allowed_cross_locale_identical_cluster(["pl", "cs", "de"], "browser")

    # --- Malay-Indonesian {id, ms} ---

    def test_id_ms_shared_tech_loanwords(self):
        for term in ("app", "browser", "cache", "chat", "data", "download", "email"):
            assert is_allowed_cross_locale_identical_cluster(["id", "ms"], term), term

    def test_id_ms_unknown_term_not_allowed(self):
        assert not is_allowed_cross_locale_identical_cluster(["id", "ms"], "terima kasih")

    def test_id_ms_does_not_cover_tr(self):
        assert not is_allowed_cross_locale_identical_cluster(["id", "ms", "tr"], "browser")

    # --- Existing groups still work ---

    def test_existing_es_fr_group_unchanged(self):
        assert is_allowed_cross_locale_identical_cluster(["es", "fr"], "bien")

    def test_existing_de_fr_group_unchanged(self):
        assert is_allowed_cross_locale_identical_cluster(["de", "fr"], "Profil")
