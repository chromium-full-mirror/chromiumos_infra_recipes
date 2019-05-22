# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools

from recipe_engine import recipe_test_api


class GitFootersTestApi(recipe_test_api.RecipeTestApi):
  """Generates test data for GitFootersApi."""

  def output(self, *args):
    return self.m.raw_io.stream_output('\n'.join(args))

  def output_factory(self, *args):
    return functools.partial(self.output, *args)
