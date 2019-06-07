# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for easy steps."""

from recipe_engine import recipe_api


class EasyApi(recipe_api.RecipeApi):
  """A module for easy steps."""

  def set_property_step(self, property_name, value, step_name=None):
    """An empty step to set a property in output.properties.

    Args:
      property_name (str): The name of the property.
      value: The value of the property to be set. Can be
        int, float, list, or dict.
      step_name (str): The name of the step.
    """
    if not step_name:
      step_name = 'set ' + property_name
    step = self.m.step(step_name, cmd=None)
    step.presentation.properties[property_name] = value

  def step(self, name, cmd, stdin=None, stdin_data=None, stdin_json=None,
           **kwargs):
    """Convenience features on top of the normal 'step' call.

    At most one of |stdin|, |stdin_data|, or |stdin_json| may be specified.

    Args:
      * name (str): The name of the step.
      * cmd (list[str]): The command to run.
      * stdin (Placeholder): Placeholder to read step stdin from.
      * stdin_data (str): Bytes to pass to stdin.
      * stdin_json (dict|list): Object to JSON-serialize to stdin.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      See 'step.__call__'.
    """
    stdins = [stdin, stdin_data, stdin_json]
    assert stdins.count(None) >= len(stdins)-1, \
      'use at most one of stdin, stdin_data, stdin_json'

    if stdin_data is not None:
      stdin = self.m.raw_io.input(stdin_data)
    elif stdin_json is not None:
      stdin = self.m.json.input(stdin_json)

    return self.m.step(name, cmd, stdin=stdin, **kwargs)

  def stdout_step(self, name, cmd, step_test_data=None, test_stdout=None,
                  **kwargs):
    """Runs an easy.step and returns stdout data.

    Args:
      * name (str): The name of the step.
      * cmd (list[str]): The command to run.
      * step_test_data (Callable): See 'step.__call__'.
      * test_stdout (str|Callable): Data to return in tests.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      str: Raw stdout data.
    """
    assert step_test_data is None or test_stdout is None, \
      'step_test_data and test_stdout are mutually exclusive'
    if test_stdout is not None:
      test_stdout = maybe_lazy_test_data(test_stdout)
      step_test_data = (
          lambda: self.m.raw_io.test_api.stream_output(test_stdout()))
    step_data = self.step(name, cmd, stdout=self.m.raw_io.output(),
                          step_test_data=step_test_data, **kwargs)
    return step_data.stdout

  def stdout_json_step(self, name, cmd, step_test_data=None, test_stdout=None,
                       **kwargs):
    """Runs an easy.step and returns stdout data deserialized from JSON.

    Args:
      * name (str): The name of the step.
      * cmd (list[str]): The command to run.
      * step_test_data (func): See 'step.__call__'.
      * test_stdout (dict|list|Callable): Data to return in tests.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      dict|list: JSON-deserialized stdout data.
    """
    assert step_test_data is None or test_stdout is None, \
      'step_test_data and test_stdout are mutually exclusive'
    if test_stdout is not None:
      test_stdout = maybe_lazy_test_data(test_stdout)
      step_test_data = (
          lambda: self.m.json.test_api.output_stream(test_stdout()))
    step_data = self.step(name, cmd, stdout=self.m.json.output(),
                          step_test_data=step_test_data, **kwargs)
    return step_data.stdout


def maybe_lazy_test_data(test_data):
  """Wraps test_data in a lambda if it isn't already callable."""
  if not hasattr(test_data, '__call__'):
    return lambda: test_data
  return test_data
