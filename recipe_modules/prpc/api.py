# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the 'prpc' tool."""

from google.protobuf import json_format

from recipe_engine import recipe_api


class PrpcApi(recipe_api.RecipeApi):
  """A module for interacting with the prpc tool."""

  @property
  def _prpc_path(self):
    """Returns the path to the prpc tool."""
    return self.m.depot_tools.package_repo_resource('prpc')

  def call_json(self, server, method, input_data, test_output_data=None):
    """Make a prpc call with JSON data.

    Args:
      server (str): The host to make the call against.
      method (str): The full method name (service.method) to call.
      input_data (str): The input JSON message data.
      test_output_data (str|func): The output data to return in a test.

      Returns:
        str: The output JSON message data.
    """
    name = 'prpc %s' % method
    cmd = [self._prpc_path, 'call', '-format', 'json', server, method]
    return self.m.easy.stdout_step(name, cmd, stdin_data=input_data,
                                   test_stdout=test_output_data)

  def call_proto(self, server, method, input_msg, output_msg_type,
                 test_output_msg=None):
    """Make a prpc call with proto Messages.

    Args:
      server (str): The host to make the call against.
      method (str): The full method name (service.method) to call.
      input_msg (google.protobuf.message.Message): The input Message.
      output_msg_type (type): The output Message type.
      test_output_msg (google.protobuf.message.Message): The output Message to
        return in a test.

      Returns:
        str: The output JSON message data.
    """
    input_data = json_format.MessageToJson(input_msg)
    test_output_data = None
    if test_output_msg is not None:
      test_output_data = json_format.MessageToJson(test_output_msg)
    output_data = self.call_json(server, method, input_data,
                                 test_output_data=test_output_data)
    output_msg = output_msg_type()
    json_format.Parse(output_data, output_msg, ignore_unknown_fields=True)
    return output_data
