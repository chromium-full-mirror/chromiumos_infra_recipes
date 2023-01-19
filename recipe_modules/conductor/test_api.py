# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
from typing import List, Dict

from recipe_engine import recipe_test_api


class ConductorTest(recipe_test_api.RecipeTestApi):
  """Helpers for testing the conductor module."""

  def set_collect_output(self, bbids: List, report: Dict = None,
                         step_name: str = ''):
    step_name = '%sread output json' % (step_name + '.' if step_name else '')
    output = {'bbids': [str(bbid) for bbid in bbids]}
    if report:
      output['report'] = report
    data = json.dumps(output)
    return self.step_data(step_name, self.m.file.read_text(data))
