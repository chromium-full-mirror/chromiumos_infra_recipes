# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that opportunistically tries CQ runs on qualified CLs."""

from typing import Generator
from typing import Optional

from PB.recipe_engine.result import RawResult
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import TestData

DEPS = ['auto_runner_util', 'easy']


def RunSteps(api: RecipeApi) -> Optional[RawResult]:
  eligible_cls = api.auto_runner_util.get_eligible_cls()
  eligible_cls_info = [{
      'change': cl.change,
      'revision_number': cl.current_revision_number
  } for cl in eligible_cls]
  api.easy.set_properties_step('Log eligible CLs in output property',
                               eligible_cls=eligible_cls_info)
  api.auto_runner_util.auto_dry_run_cls(eligible_cls)


def GenTests(api: RecipeApi) -> Generator[TestData, None, None]:
  yield api.test('basic', api.post_process(post_process.DropExpectation))
