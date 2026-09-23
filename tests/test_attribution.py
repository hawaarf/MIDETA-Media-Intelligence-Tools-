# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_HEADER = (
    "# Copyright (c) 2026 Hawarisma Rafanidya Singgih\n"
    "# SPDX-License-Identifier: MIT\n"
)
CSS_HEADER = (
    "/* Copyright (c) 2026 Hawarisma Rafanidya Singgih */\n"
    "/* SPDX-License-Identifier: MIT */\n"
)


class AttributionTests(unittest.TestCase):
    def test_python_sources_keep_attribution_header(self):
        paths = [ROOT / "app.py"]
        paths.extend(sorted((ROOT / "pages").glob("*.py")))
        paths.extend(sorted((ROOT / "src").rglob("*.py")))
        paths.extend(sorted((ROOT / "tests").glob("*.py")))

        missing = [
            str(path.relative_to(ROOT))
            for path in paths
            if not path.read_text(encoding="utf-8").startswith(PYTHON_HEADER)
        ]
        self.assertEqual(missing, [], f"Attribution header missing from: {missing}")

    def test_css_and_streamlit_config_keep_attribution_header(self):
        css = (ROOT / "assets" / "styles.css").read_text(encoding="utf-8")
        config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        self.assertTrue(css.startswith(CSS_HEADER))
        self.assertTrue(config.startswith(PYTHON_HEADER))

    def test_legal_and_visible_attribution_remain_present(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        attribution = (ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
        ui = (ROOT / "src" / "ui.py").read_text(encoding="utf-8")

        owner = "Hawarisma Rafanidya Singgih"
        self.assertIn(f"Copyright (c) 2026 {owner}", license_text)
        self.assertIn(f"created and developed by **{owner}**", attribution)
        self.assertIn(f"Developed by {owner}", ui)


if __name__ == "__main__":
    unittest.main()
