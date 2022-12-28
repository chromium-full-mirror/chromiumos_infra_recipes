# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
from typing import Any, Dict

from recipe_engine import recipe_test_api


class CrosResultdbTestApi(recipe_test_api.RecipeTestApi):

  def resultdb_settings_arg(self, resultdb_settings: Dict[str, Any]) -> str:
    """Return a resultdb_settings={} arg that encodes the given settings."""
    settings_json: str = self.m.json.dumps(resultdb_settings)
    settings_b64: str = base64.b64encode(settings_json.encode()).decode()
    return f'resultdb_settings={settings_b64}'
