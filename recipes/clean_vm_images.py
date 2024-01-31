# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for cleaning up stale GCP VM images."""

import json
from typing import Generator, Optional

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'build_menu',
    'vmlab',
]



def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  result = api.vmlab.clean_images('cleanup outdated images',
                                  api.build_menu.is_staging, 1)
  return RawResult(status=common.SUCCESS, summary_markdown=json.dumps(result))


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  yield api.test('clean-vm-images')
