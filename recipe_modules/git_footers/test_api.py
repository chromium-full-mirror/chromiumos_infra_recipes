# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools

from recipe_engine import recipe_test_api


class GitFootersTestApi(recipe_test_api.RecipeTestApi):
  """Generates test data for GitFootersApi."""

  test_position_num = 101

  def step_data(self, name, *args, **kwargs):
    return super(GitFootersTestApi,
                 self).step_data(name,
                                 stdout=self.m.raw_io.output('\n'.join(args)),
                                 **kwargs)

  def step_test_data(self, *args):
    return self.m.raw_io.stream_output('\n'.join(args))

  def step_test_data_factory(self, *args):
    return functools.partial(self.step_test_data, *args)

  def simulated_get_footers(self, footers, parent_step_name=None,
                            step_number=None):
    """Simulates getting git footers.

    Args:
      footers(list[str]): List of footers to be output by the step.
      parent_step_name (str): Parent of the step to set step_data for.
      step_number (int): Suffix for the step name.

    Returns:
      StepData: Resulting step data.
    """
    if not parent_step_name:
      step_name = 'read git footers'
    else:
      step_name = '%s.read git footers' % parent_step_name
    if step_number and step_number != 1:
      step_name = '%s (%d)' % (step_name, step_number)
    return self.step_data(step_name, *footers)
