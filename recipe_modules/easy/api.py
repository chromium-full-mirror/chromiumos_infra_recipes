# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for easy steps."""

from typing import Any, Dict, List, Optional, Union

from recipe_engine import recipe_api, step_data
from google.protobuf import json_format


class EasyApi(recipe_api.RecipeApi):
  """A module for easy steps."""

  def set_properties_step(self, step_name: Optional[str] = None,
                          **kwargs) -> step_data.StepData:
    """An empty step to set properties in output.properties.

    Args:
      step_name: The name of the step.
      kwargs: Keyword arguments to set as properties, key is property name
          and value is property value. Key must be a string, value may be
          str, int, float, list, or dict.
          If value is bytes, it will be cast to string.

    Returns:
      See 'step.__call__'.
    """
    if not step_name:
      if len(kwargs) == 1:
        step_name = 'set ' + list(kwargs.keys())[0]
      else:
        step_name = 'set properties'
    step = self.m.step(step_name, cmd=None)
    for k, v in kwargs.items():
      if isinstance(v, bytes):
        v = v.decode()
      elif isinstance(v, list):
        for i, elem in enumerate(v):
          if isinstance(elem, bytes):
            v[i] = elem.decode()
      step.presentation.properties[k] = v
    return step

  def step(self, name: str, cmd: List[str], stdin: Optional[Any] = None,
           stdin_data: Optional[str] = None, stdin_json: Optional[Any] = None,
           **kwargs) -> step_data.StepData:
    """Convenience features on top of the normal 'step' call.

    At most one of |stdin|, |stdin_data|, or |stdin_json| may be specified.

    Args:
      * name: The name of the step.
      * cmd: The command to run.
      * stdin: Placeholder to read step stdin from.
      * stdin_data: Bytes to pass to stdin.
      * stdin_json: Object to JSON-serialize to stdin.
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

  def stdout_step(self, name: str, cmd: List[str],
                  step_test_data: Optional[Any] = None,
                  test_stdout: Optional[Union[str, Any]] = None,
                  **kwargs) -> bytes:
    """Runs an easy.step and returns stdout data.

    Args:
      * name: The name of the step.
      * cmd: The command to run.
      * step_test_data: Should be 'callable', See 'step.__call__'.
      * test_stdout: Data to return in tests.
      * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      bytes: Raw stdout data.
    """
    assert step_test_data is None or test_stdout is None, \
      'step_test_data and test_stdout are mutually exclusive'
    if test_stdout is not None:
      test_stdout = maybe_lazy_test_data(test_stdout)
      step_test_data = (
          lambda: self.m.raw_io.test_api.stream_output(test_stdout()))
    sd = self.step(name, cmd, stdout=self.m.raw_io.output(),
                   step_test_data=step_test_data, **kwargs)
    return sd.stdout

  def stdout_json_step(self, name: str, cmd: List[str],
                       step_test_data: Optional[Any] = None,
                       test_stdout: Optional[Union[str, Any]] = None,
                       ignore_exceptions: bool = False,
                       **kwargs) -> Union[Dict, List]:
    """Runs an easy.step and returns stdout data deserialized from JSON.

    Args:
      * name: The name of the step.
      * cmd: The command to run.
      * step_test_data: Should be 'callable', See 'step.__call__'.
      * test_stdout: Data to return in tests.a
      * ignore_exceptions: Should we ignore any exceptions.
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
    sd = self.step(name, cmd, stdout=self.m.json.output(),
                   step_test_data=step_test_data, ok_ret=ok_ret, **kwargs)
    return sd.stdout

  def stdout_jsonpb_step(self, name: str, cmd: List[str], message_type: type,
                         test_output: Optional[Any] = None,
                         parse_before_str: str = '', **kwargs) -> Any:
    """Runs an easy.step and returns stdout jsonpb-deserialized proto data.

    * name (str): The name of the step.
    * cmd (list[str]): The command to run.
    * message_type: A type (and also constructor) of proto message, indicating
      the type of proto to be returned.
    * test_output: Data, of type(message_type), to return in tests.
    * parse_before_str: Parse value only upto this str. Used to bypass random binaries appended with protos.
    * kwargs: Keyword arguments to pass to the 'step' call.

    Returns:
      message_type: JSON-pb deserialized proto message.
    """
    assert isinstance(message_type, type), 'message_type must be a type'

    test_output_str = None
    if test_output is not None:
      test_output_str = json_format.MessageToJson(test_output)

    output = message_type()
    sd = self.stdout_step(name, cmd, test_stdout=test_output_str, **kwargs)
    #TODO(b/225967293): Interim fix before figuring out root cause.
    # Remove after root case is identified.
    if parse_before_str:
      sd = sd.split(parse_before_str)[0]  # pragma: no cover
    return json_format.Parse(sd, output, ignore_unknown_fields=True)

  # TODO(crbug/1322624): Clean up when LUCI supports this for free.
  def log_parent_step(self, log_if_no_parent: bool = True) -> None:
    """Creates a short step to log the current builder's parent build ID.

    Args:
      log_if_no_parent: If True and there is no parent build, create an empty
        step stating that there's no parent build. If False and there is no
        parent build, do nothing.
    """
    parent_id = self.m.cros_tags.get_single_value('parent_buildbucket_id')
    if parent_id:
      with self.m.step.nest('Parent build: {}'.format(parent_id)) as pres:
        pres.links[parent_id] = self.m.buildbucket.build_url(build_id=parent_id)
    elif log_if_no_parent:
      self.m.step.empty('No parent build.')


def maybe_lazy_test_data(test_data: Any) -> Any:
  """Wraps test_data in a lambda if it isn't already callable."""
  if not hasattr(test_data, '__call__'):
    return lambda: test_data
  return test_data
