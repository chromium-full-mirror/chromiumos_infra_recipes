# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class GitClTestApi(recipe_test_api.RecipeTestApi):

  def output(self, step_name, output):
    return self.step_data(step_name, self.m.raw_io.stream_output(output))
