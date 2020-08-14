# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for easy steps."""

from recipe_engine import recipe_api
from google.protobuf import json_format


class EasyApi(recipe_api.RecipeApi):
  """A module for easy steps."""

  def set_properties_step(self, step_name=None, **kwargs):
    """An empty step to set properties in output.properties.

    Args:
      step_name (str): The name of the step.
      kwargs: Keyword arguments to set as properties, key is property name
          and value is property value. Key must be a string, value may be
          int, float, list, or dict.

    Returns:
      See 'step.__call__'.
    """
    if not step_name:
      if len(kwargs) == 1:
        step_name = 'set ' + kwargs.keys()[0]
      else:
        step_name = 'set properties'
    step = self.m.step(step_name, cmd=None)
    for k, v in kwargs.iteritems():
      step.presentation.properties[k] = v
    return step

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
                       ignore_exceptions=False, **kwargs):
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
    ok_ret = {0}
    if ignore_exceptions:
      ok_ret = 'any'
    step_data = self.step(name, cmd, stdout=self.m.json.output(),
                          step_test_data=step_test_data, ok_ret=ok_ret,
                          **kwargs)
    return step_data.stdout

  def stdout_jsonpb_step(self, name, cmd, message_type, test_output=None,
                         **kwargs):
    """Runs an easy.step and returns stdout jsonpb-deserialized proto data.

    * name (str): The name of the step.
    * cmd (list[str]): The command to run.
    * message_type: A type (and also constructor) of proto message, indicating
      the type of proto to be returned.
    * test_output (message_type): Data to return in tests.
    * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      message_type: JSON-pb deserialized proto message.
    """
    assert isinstance(message_type, type), 'message_type must be a type'

    test_output_str = None
    if test_output is not None:
      test_output_str = json_format.MessageToJson(test_output)

    output = message_type()
    step_data = self.stdout_step(name, cmd, test_stdout=test_output_str,
                                 **kwargs)
    return json_format.Parse(step_data, output, ignore_unknown_fields=True)


def maybe_lazy_test_data(test_data):
  """Wraps test_data in a lambda if it isn't already callable."""
  if not hasattr(test_data, '__call__'):
    return lambda: test_data
  return test_data
