# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_test_api


class ConductorTest(recipe_test_api.RecipeTestApi):
  """Helpers for testing the conductor module."""

  def set_collect_output(self, bbids, step_name=None):
    step_name = '%sread output json' % (step_name + '.' if step_name else '')
    data = json.dumps({'bbids': [str(bbid) for bbid in bbids]})
    return self.step_data(step_name, self.m.file.read_text(data))
