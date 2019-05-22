# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools

from recipe_engine import recipe_test_api


class GitFootersTestApi(recipe_test_api.RecipeTestApi):
  """Generates test data for GitFootersApi."""

  def step_data(self, name, *args):
    return super(GitFootersTestApi, self).step_data(
        name, stdout=self.m.raw_io.output('\n'.join(args)))

  def step_test_data(self, *args):
    return self.m.raw_io.stream_output('\n'.join(args))

  def step_test_data_factory(self, *args):
    return functools.partial(self.step_test_data, *args)
