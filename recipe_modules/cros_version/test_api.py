# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import textwrap

from recipe_engine import recipe_test_api


class CrosVersionTestApi(recipe_test_api.RecipeTestApi):

  # Example chromeos_version.sh with historically-accurate contents.
  chromeos_version_contents = textwrap.dedent(r'''\
    if something; then
      # Comment
      export CHROMEOS_BUILD=1234
      # Other Comment
      CHROMEOS_BRANCH=56
      CHROMEOS_PATCH=0  # inline comment
    fi

    export CHROME_BRANCH=99
    ''')
