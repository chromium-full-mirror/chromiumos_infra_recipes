# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the protobuf-based Build API."""

from collections import namedtuple
import functools

from google.protobuf import descriptor_pool
from google.protobuf import json_format
from google.protobuf import reflection
from google.protobuf import timestamp_pb2

from recipe_engine import recipe_api

from PB.chromite.api import api as meta_api

def _verify_proto_endpoint(instance, method):
  """Verifies that the method exists as proto endpoint.

  Verifies that the method exists as a proto endpoint within the Stub purely
  from a protocol buffer definition standpoint. If it does not exist a
  `KeyError` is thrown.

  Args:
    instance (Stub): The instance to check.
    method (str): Name of method to check for.

  Returns:
    service, method_descriptor if found, otherwise throws
        `KeyError`.
  """
  service = 'chromite.api.%s' % type(instance).__name__
  # Check that the service and method exist.
  service_descriptor = descriptor_pool.Default().FindServiceByName(service)
  method_descriptor = service_descriptor.FindMethodByName(method)
  if not method_descriptor:
    raise KeyError('no such method %s in service %s' % (method, service))
  return service, method_descriptor

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
    service, method_descriptor = _verify_proto_endpoint(self, method)

    # Check that the input type aligns with what is expected.
    given_input_type = input_proto.DESCRIPTOR.full_name
    method_input_type = method_descriptor.input_type.full_name
    if given_input_type != method_input_type:
      raise TypeError('expected input type %r, got %r' % (method_input_type,
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


class MethodService(Stub):
  """Stub for MethodService."""


# Note that HasPrebuilt was exposed in chromite in https://crrev.com/c/2116663
# and has_endpoint checks should be used.
class PackageService(Stub):
  """Stub for PackageService."""


class ImageService(Stub):
  """Stub for ImageService."""


class SdkService(Stub):
  """Stub for SdkService."""


class SysrootService(Stub):
  """Stub for SysrootService."""


class TestService(Stub):
  """Stub for TestService."""


class ToolchainService(Stub):
  """Stub for ToolchainService."""


class VersionService(Stub):
  """Stub for VersionService."""


class CrosBuildApiApi(recipe_api.RecipeApi):
  """This recipe module exposes client stubs for all build API services.

  To add a service endpoint, create a class INSIDE THIS MODULE extending Stub.
  Make sure the class name is the same as the service name.

  To call a service endpoint, call the corresponding method on the stub. It
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

  def __init__(self, properties, *args, **kwargs):
    super(CrosBuildApiApi, self).__init__(*args, **kwargs)
    self._capture_stdout_stderr = properties.capture_stdout_stderr
    self._log_level = properties.log_level or 'debug'
    self._endpoints = None
    self._version = None

  version_tuple = namedtuple('verison_tuple', ['major', 'minor', 'bug'])
  @property
  def version(self):
    if not self._version:
      version_resp = self('chromite.api.VersionService/Get',
                          meta_api.VersionGetRequest(),
                          meta_api.VersionGetResponse.DESCRIPTOR,
                          infra_step=True)
      version = version_resp.version
      self._version = self.version_tuple(version.major or 0, version.minor or 0,
                                         version.bug or 0)
    return self._version

  def __call__(self, endpoint, input_proto, output_type, test_output_data=None,
               test_teelog_data=None, name=None, infra_step=False,
               timeout=None, response_lambda=None):
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
      test_teelog_data (str): Text to use as tee-log contents during testing.
      name (str): Name for the step. Generated automatically if not specified.
      infra_step (bool): Whether this build API call should be treated as an
          infrastructure step.
      timeout (int): timeout in seconds to be supplied to the BuildAPI call.
      response_lambda (fn(output_proto)->str): A function that appends a string
          to the build api response step. Used to make failure step names unique
          across differing root causes.

    Returns:
      google.protobuf: The parsed response proto.
    """
    response_lambda = response_lambda or (lambda op: '')

    with self.m.step.nest(name or 'call %s' % endpoint) as presentation:
      messages_path = self.m.path.mkdtemp(prefix='build_api_messages')
      input_path = messages_path.join('input_proto.json')
      output_path = messages_path.join('output_proto.json')
      logfile_path = messages_path.join('build_log.txt')

      # Write the input proto JSON to a temp file (which is how it's passed to
      # the build API) and record it to the step logs for debugging.
      input_json = json_format.MessageToJson(input_proto)
      self.m.file.write_raw('write input file', input_path, input_json)
      presentation.logs['request'] = [input_json]
      presentation.logs['response'] =  ['{}']

      cmd = [
          self.m.cros_source.workspace_path.join('chromite/bin/build_api'),
          '--input-json', input_path, '--output-json', output_path,
          '--log-level', self._log_level
      ]
      if self._capture_stdout_stderr:
        cmd.extend(['--tee-log', logfile_path])
      cmd.append(endpoint)
      file_contents = None

      # build_api needs to invoke other chromite/bin binaries, hence this dir
      # needs to be on the PATH.
      chromite_bin_dir = self.m.cros_source.workspace_path.join('chromite/bin')
      with self.m.context(env_suffixes={'PATH': [chromite_bin_dir]}):
        try:
          output_proto = reflection.MakeClass(output_type)()
          # For Build API retcode 2 indicates that the invocation failed in some
          # way but a consumable response has been produced.
          request_time = timestamp_pb2.Timestamp()
          request_time.FromDatetime(self.m.time.utcnow())
          try:
            call_step = self.m.step('call build API script', cmd, ok_ret=(0, 2),
                                    infra_step=infra_step, timeout=timeout)
          finally:
            response_time = timestamp_pb2.Timestamp()
            response_time.FromDatetime(self.m.time.utcnow())

          if self._capture_stdout_stderr:
            file_contents = self.m.file.read_raw('read tee output file',
                                                 logfile_path,
                                                 test_data=test_teelog_data)

          # If no test data is provided, see if we have our own.
          test_output_data = (test_output_data or
                              self.test_api.response_for_endpoint(endpoint))

          # Parse the output to a proto and record it in the logs.
          output_json = self.m.file.read_raw('read output file', output_path,
                                            test_data=test_output_data)

          json_format.Parse(output_json, output_proto,
                            ignore_unknown_fields=True)

          # Since we can't rename the api step, and certain applications\tables
          # have taken them as input (e.g. sheriff-o-matic), we then make a
          # 'response' step that we can have foreknowledge of what the name
          # _should_ be based on the call's results.
          presentation.logs['response'] = [output_json]
          resp_step_name = self.response_step_name(output_proto,
                                                   response_lambda)

          with self.m.step.nest(resp_step_name) as resp_pres:
            resp_pres.logs['build api stdout'] = ('' if not file_contents
                                                  else file_contents)
            if call_step.exc_result.retcode != 0:
              resp_pres.status = self.m.step.FAILURE

        except self.m.step.StepFailure as e:
          call_step = e.result
          raise e

        finally:
          # Publish Build API responses on Cloud Pub/Sub if they are registered.
          if self.m.analysis_service.can_publish_event(input_proto,
                                                       output_proto):
            self.m.analysis_service.publish_event(input_proto, output_proto,
                                                  request_time, response_time,
                                                  call_step, file_contents)

      return output_proto

  def response_step_name(self, output_proto, response_lambda):
    return 'call response%s' % response_lambda(output_proto)

  def has_endpoint(self, stub, method):
    """Verifies that the given endpoint can be called.

    Args:
      stub (Stub): stub instance to check if `method` can be called on it.
      method (str): name of method to check for.

    Returns:
      bool: Whether `method` can be called on `stub`.
    """
    # First check that stub is really a Stub registered with the API.
    stub_name = type(stub).__name__
    if not isinstance(stub, Stub) or not getattr(self, stub_name, None) == stub:
      return False

    # Next make sure that the proto defs exist for the method.
    try:
      service_name, _ = _verify_proto_endpoint(stub, method)
    except:
      return False

    # Lastly, check that the build API side implements the endpoint.
    # The list of endpoints is lazily cached here.
    if not self._endpoints:
      response = self.MethodService.Get(meta_api.MethodGetRequest())
      self._endpoints = [m.method for m in response.methods]

    return "%s/%s" % (service_name, method) in self._endpoints
