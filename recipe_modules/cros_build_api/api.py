# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the protobuf-based Build API."""

import functools
import json

from google.protobuf import descriptor_pool
from google.protobuf import json_format
from google.protobuf import reflection

from recipe_engine import recipe_api


class Stub(object):
  """A simple client stub for the build API.

  This class should have one subclass for each service. It determines the exact
  build API endpoint to call based on the name of the class (which MUST match
  the service name) and the method called on it (which MUST match the service
  method to call). It validates that the input proto type matches what the
  service expects.
  """

  def __init__(self, call_build_api):
    # call_build_api is a function that (blindly) writes the proto to
    # file, calls the build API command line, and reads the output. This
    # needs to be a callback because non-RecipeApi classes cannot use the
    # injected modules such as recipe_modules/file
    self._call_build_api = call_build_api

  def __call__(self, method, input_proto, **kwargs):
    service = 'chromite.api.%s' % type(self).__name__

    # Check that the service and method exist.
    service_descriptor = descriptor_pool.Default().FindServiceByName(service)
    method_descriptor = service_descriptor.FindMethodByName(method)
    if method_descriptor is None:
      raise KeyError('No such method %s in service %s.' % (method, service))

    # Check that the input type aligns with what is expected.
    given_input_type = input_proto.DESCRIPTOR.full_name
    method_input_type = method_descriptor.input_type.full_name
    if given_input_type != method_input_type:
      raise TypeError('Expected input type %r, got %r' % (method_input_type,
                                                          given_input_type))

    # We good we good we good. Now we can actually call the build API.
    endpoint = '%s/%s' % (service, method)
    return self._call_build_api(endpoint, input_proto,
                                method_descriptor.output_type, **kwargs)

  def __getattr__(self, attr):
    return functools.partial(self, attr)


class ArtifactsService(Stub):
  """Stub for ArtifactsService."""


class BinhostService(Stub):
  """Stub for BinhostService."""


class DependencyService(Stub):
  """Stub for DependencyService."""


class ImageService(Stub):
  """Stub for ImageService."""


class SdkService(Stub):
  """Stub for SdkService."""


class SysrootService(Stub):
  """Stub for SysrootService."""


class TestService(Stub):
  """Stub for TestService."""


class CrosBuildApiApi(recipe_api.RecipeApi):
  """This recipe module exposes client stubs for all build API services.

  To add a service endpoint, create a class INSIDE THIS MODULE extending Stub.
  Make sure the class name is the same as the service name.

  To call a service endpoint, simply call corresponding method on the stub. It
  will "magicly" know what to do and fail gracefully if it does not. Example:

      # Inside recipes/my_recipe.py...
      my_request_proto = BundleRequest()
      # Set up your request proto, and then...
      api.cros_build_api.ArtifactsService.BundleFirmware(my_request_proto)

  The stub will perform sane validations and then call the build API command.
  """

  def initialize(self):
    """Expose all client stubs defined in this module."""
    stubs = Stub.__subclasses__()
    for stub in stubs:
      setattr(self, stub.__name__, stub(self))

  def __call__(self, endpoint, input_proto, output_type, test_output_data=None,
               name=None, infra_step=False, timeout=None):
    """Call the build API with the given input proto.

    This function tries to be as dumb as possible. It does not validate that
    the endpoint exists, nor that the input_proto has the correct type. While
    clients may call this function directly, they should ALMOST ALWAYS call
    the build API through the appropriate stub.

    Args:
      endpoint (str): The full endpoint to call,
          e.g. chromite.api.MyService/MyMethod
      input_proto (google.protobuf): The input proto object.
      output_type (google.protobuf.descriptor): The output proto type.
      test_output_data (str): JSON to use as a response during testing.
      name (str): Name for the step. Generated automatically if not specified.
      infra_step (bool): Whether this build API call should be treated as an
          infrastructure step.
      timeout (int): timeout in seconds to be supplied to the BuildAPI call.

    Returns:
      google.protobuf: The parsed response proto.
    """
    with self.m.step.nest(name or 'call %s' % endpoint) as step:
      messages_path = self.m.path.mkdtemp(prefix='build_api_messages')
      input_path = messages_path.join('input_proto.json')
      output_path = messages_path.join('output_proto.json')

      # Write the input proto JSON to a temp file (which is how it's passed to
      # the build API) and record it to the step logs for debugging.
      input_json = json_format.MessageToJson(input_proto)
      self.m.file.write_raw('write input file', input_path, input_json)
      step.presentation.logs['request'] = [input_json]

      cmd = [
          self.m.cros_source.workspace_path.join('chromite/bin/build_api'),
          '--input-json', input_path, '--output-json', output_path, endpoint
      ]

      # build_api needs to invoke other chromite/bin binaries, hence this dir
      # needs to be on the PATH.
      chromite_bin_dir = self.m.cros_source.workspace_path.join('chromite/bin')
      with self.m.context(env_suffixes={'PATH': [chromite_bin_dir]}):
        # For Build API retcode 2 indicates that the invocation failed in some
        # way but a consumable response has been produced.
        self.m.step('call build API script', cmd, ok_ret=(0, 2),
                    infra_step=infra_step, timeout=timeout)

      # If no test data is provided, see if we have our own.
      if test_output_data is None:
        test_output_data = self.test_api.response_for_endpoint(endpoint)

      # Finally, parse the output to a proto and record it in the logs.
      output_json = self.m.file.read_raw('read output file', output_path,
                                         test_data=test_output_data)
      step.presentation.logs['response'] = [output_json]
      output_proto = reflection.MakeClass(output_type)()
      json_format.Parse(output_json, output_proto)

      # Publish Build API responses on Cloud Pub/Sub if they are registered.
      #
      # Catch exceptions, as this functionality is just being tested out right
      # now.
      # TODO(crbug.com/964444): Remove try once this is stable.
      try:
        if self.m.analysis_service.can_publish_event(input_proto, output_proto):
          self.m.analysis_service.publish_event(input_proto, output_proto)
      except Exception as e:
        step.presentation.logs['Failure reason'] = [repr(e)]

      return output_proto
