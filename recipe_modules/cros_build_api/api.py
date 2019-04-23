# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the protobuf-based Build API."""

import json

from google.protobuf import descriptor_pool
from google.protobuf import json_format
from google.protobuf import reflection

from recipe_engine import recipe_api


class CrosBuildApiApi(recipe_api.RecipeApi):
  """A module for CrOS Build API steps."""

  def _call(self, service_method, input_data, test_output_data=''):
    """Call a Build API method.

    Args:
      service_method (str): The service/method path (ex.
          chromium.api.Service/Method).
      input_data (str): Input data.
      test_output_data (str): Data to return during test.

    Returns:
      str: Output data.
    """
    messages_path = self.m.path.mkdtemp(prefix='build_api_messages')
    input_path = messages_path.join('input_proto.json')
    output_path = messages_path.join('output_proto.json')

    # Write the input proto JSON to a temp file (which is how it's passed to
    # the build API).
    self.m.file.write_raw('write input file', input_path, input_data)

    bin_path = self.m.cros_source.workspace_path.join('chromite/bin/build_api')
    build_api_cmd = [
        bin_path, '--input-json', input_path, '--output-json', output_path,
        service_method
    ]
    # TODO(crbug.com/950959): Because the chroot runs as root, the build API
    # must also run as root, lest it access chroot files with insufficient
    # permissions. An unfortunate consequence is that we must set the umask
    # so that files created by the build API are readable by the parent process.
    # Hence, the horrid command.
    cmd = [
        'sudo', '/bin/bash', '-c',
        'umask 0000 && %s' % ' '.join(map(str, build_api_cmd))
    ]
    self.m.step('build_api %s' % service_method, cmd)

    return self.m.file.read_raw('read output file', output_path,
                                test_data=test_output_data)

  def call_json(self, service_method, input_dict, test_output_dict=None):
    """Call a Build API method with JSON serialization.

    For now, only runs outside the chroot (crbug.com/949789).

    Args:
      service_method (str): The service/method path (ex.
          chromium.api.Service/Method).
      input_dict (dict): Input data.
      test_output_dict (dict): Data to return during test.

    Returns:
      dict: Output data.
    """
    output_data = self._call(service_method, json.dumps(input_dict),
                             test_output_data=json.dumps(test_output_dict))
    return json.loads(output_data)

  def _method_descriptor(self, service_method):
    """Lookup a |google.protobuf.descriptor.ServiceDescriptor|.

    The module containing the service descriptor must be imported before this
    is called.

    Args:
      service_method (str): The service/method path (ex.
          chromium.api.Service/Method).

    Raises:
      KeyError: If the service name isn't found.
    """
    service_name, method_name = service_method.split('/')
    try:
      svc_descriptor = descriptor_pool.Default().FindServiceByName(service_name)
    except KeyError as e:
      # The KeyError raised by FindServiceByName only has the package name.
      raise KeyError('%r; did you import the module?' % service_name, e)

    return svc_descriptor.FindMethodByName(method_name)

  def call_proto(self, service_method, input_msg, test_output_data='{}'):
    """Call a Build API method with JSON serialization.

    For now, only runs outside the chroot (crbug.com/949789).

    Args:
      service_method (str): The service/method path (ex.
          chromium.api.Service/Method).
      input_msg (google.protobuf.message.Message): Input data.
      test_output_data (str): Data to return during test.

    Raises:
      KeyError: if the given service_method isn't found.
      TypeError: if |input_msg| is the wrong Message type.

    Returns:
      google.protobuf.message.Message: Output data.
    """
    method = self._method_descriptor(service_method)

    input_msg_type = input_msg.DESCRIPTOR.full_name
    method_input_type = method.input_type.full_name
    if input_msg_type != method_input_type:
      raise TypeError('expected input type %r, got %r' % (method_input_type,
                                                          input_msg_type))

    input_data = json_format.MessageToJson(input_msg)
    output_data = self._call(service_method, input_data,
                             test_output_data=test_output_data)
    output_msg = reflection.MakeClass(method.output_type)()
    return json_format.Parse(output_data, output_msg)
