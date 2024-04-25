# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the protobuf-based Build API."""

import functools
import hashlib
from typing import Any, Callable, List, Optional, Tuple

import contextlib

import json
from google.protobuf import descriptor
from google.protobuf import descriptor_pool
from google.protobuf import json_format
from google.protobuf import message
from google.protobuf import reflection
from google.protobuf import timestamp_pb2

from PB.chromite.api import api as meta_api
from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.cros_build_api import (cros_build_api as
                                                       cros_build_api_pb2)
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure


# By default, chromite-HEAD will bounce all calls it gets to the branched
# chromite, so we use the chromite-HEAD checkout. To update a method or
# service to use chromite-HEAD instead of branched chromite, see
# go/cros-build:use-chromite-head.
chromite_location = 'infra/chromite-HEAD'


def _verify_proto_endpoint(
    service_stub: 'Stub',
    method: str) -> Tuple[str, descriptor.MethodDescriptor]:
  """Verifies that the method exists as proto endpoint.

  Verifies that the method exists as a proto endpoint within the Stub purely
  from a protocol buffer definition standpoint.

  Args:
    service_stub: The service to check.
    method: Name of method to check for.

  Returns:
    A tuple of (service ID, method descriptor) for the given method.

  Raises:
    KeyError: If the method does not exist on this service.
  """
  service_id = 'chromite.api.%s' % type(service_stub).__name__
  # Check that the service and method exist.
  service_descriptor = descriptor_pool.Default().FindServiceByName(service_id)
  method_descriptor = service_descriptor.FindMethodByName(method)
  if not method_descriptor:
    raise KeyError('no such method %s in service %s' % (method, service_id))
  return service_id, method_descriptor


class Stub:
  """A simple client stub for the build API.

  This class should have one subclass for each service. It determines the exact
  build API endpoint to call based on the name of the class (which MUST match
  the service name) and the method called on it (which MUST match the service
  method to call). It validates that the input proto type matches what the
  service expects.
  """

  def __init__(self, call_build_api: Callable) -> None:
    """Initialize the Stub instance.

    Args:
      call_build_api: A function that (blindly) writes the proto to a file,
        calls the build API command line, and reads the output. This needs to be
        a callback because non-RecipeApi classes cannot use the injected modules
        such as recipe_modules/file/.
    """
    self._call_build_api = call_build_api

  def __call__(self, method: str, input_proto: message.Message,
               **kwargs) -> message.Message:
    """Call the given method on this service.

    Args:
      method: The name of the method, such as 'Uprev'.
      input_proto: A populated request message corresopnding to this endpoint.
      kwargs: Additional kwargs to pass into self._call_build_api.

    Returns:
      A populated response message returned by the endpoint.
    """
    service, method_descriptor = _verify_proto_endpoint(self, method)

    # Check that the input type aligns with what is expected.
    given_input_type = input_proto.DESCRIPTOR.full_name
    method_input_type = method_descriptor.input_type.full_name
    if given_input_type != method_input_type:
      raise TypeError('expected input type %r, got %r' %
                      (method_input_type, given_input_type))

    # We good we good we good. Now we can actually call the build API.
    endpoint = '%s/%s' % (service, method)
    return self._call_build_api(endpoint, input_proto,
                                method_descriptor.output_type, **kwargs)

  def __getattr__(
      self, method: str) -> Callable[[message.Message, Any], message.Message]:
    """Return a partial call of this Stub instance for a given endpoint.

    Example usage:
      class PackageService(Stub):
        pass
      PackageService.Uprev(request)
    In this case, PackageService.Uprev calls __getattr__, which returns a
    partial of PackageService.__call__ with method='Uprev'. Then that partial
    is called with input_proto=request. In short, this enables the above syntax
    as a prettier form of PackageService('Uprev', request).

    Returns:
      A callable for the given method, which takes an input proto message and
      any number of kwargs, and returns a response proto message.
    """
    return functools.partial(self, method)


class AndroidService(Stub):
  """Stub for AndroidService."""


class ApiService(Stub):
  """Stub for ApiService."""


class ArtifactsService(Stub):
  """Stub for ArtifactsService."""


class BinhostService(Stub):
  """Stub for BinhostService."""


class CopybotService(Stub):
  """Stub for CopybotService."""


class DependencyService(Stub):
  """Stub for DependencyService."""


class DlcService(Stub):
  """Stub for DlcService."""


class FirmwareService(Stub):
  """Stub for FirmwareService."""


class ObservabilityService(Stub):
  """Stub for ObservabilityService."""


class ImageService(Stub):
  """Stub for ImageService."""


class MethodService(Stub):
  """Stub for MethodService."""


# Note that HasPrebuilt was exposed in chromite in https://crrev.com/c/2116663
# and has_endpoint checks should be used.
class PackageService(Stub):
  """Stub for PackageService."""


class PayloadService(Stub):
  """Stub for PayloadService."""


class PortageExplorerService(Stub):
  """Stub for PortageExplorerService."""


class RelevancyService(Stub):
  """Stub for RelevancyService."""


class SdkService(Stub):
  """Stub for SdkService."""


class SdkSubtoolsService(Stub):
  """Stub for SdkSubtoolsService."""


class SigningService(Stub):
  """Stub for SigningService."""


class SysrootService(Stub):
  """Stub for SysrootService."""


class TestService(Stub):
  """Stub for TestService."""


class ToolchainService(Stub):
  """Stub for ToolchainService."""


class VersionService(Stub):
  """Stub for VersionService."""


@functools.total_ordering
class Version():
  """Version of the Build API."""

  def __init__(self, major: int = 1, minor: int = 1, bug: int = 0) -> None:
    """Initialize the Version instance."""
    self.major = major
    self.minor = minor
    self.bug = bug

  @property
  def _tuple(self) -> Tuple[int, int, int]:
    """Return a tuple of (major, minor, bug)."""
    return (self.major, self.minor, self.bug)

  def __eq__(self, other: Any) -> bool:
    """Return whether this Version is equal to another."""
    return self._tuple == other._tuple

  def __lt__(self, other: Any) -> bool:
    """Return whether this Version is less than another."""
    return self._tuple < other._tuple

  def __repr__(self) -> str:
    """Return a string representation of this Version."""
    return f'{self.major}.{self.minor}.{self.bug}'

  @classmethod
  def ParseVersion(cls, version: str) -> 'Version':
    """Turn a dot-delimited string version into a Version instance.

    Args:
      version: A dot-delimtied string version, such as '1.2.3'.

    Returns:
      A Version representing the input version.
    """
    major, minor, bug = version.split('.')
    return cls(int(major), int(minor), int(bug))

  def FormatResponse(self) -> meta_api.VersionGetResponse:
    """Return the API response for this version.

    Returns:
      A VersionGetResponse representing this Version.
    """
    return json_format.MessageToJson(
        meta_api.VersionGetResponse(version={
            'major': self.major,
            'minor': self.minor,
            'bug': self.bug,
        }))


class CrosBuildApiApi(RecipeApi):
  """This recipe module exposes client stubs for all build API services.

  To add a service endpoint, create a class INSIDE THIS MODULE extending Stub.
  Make sure the class name is the same as the service name.

  To call a service endpoint, call the corresponding method on the stub. It
  will "magically" know what to do and fail gracefully if it does not. Example:

      # Inside recipes/my_recipe.py...
      my_request_proto = BundleRequest()
      # Set up your request proto, and then...
      api.cros_build_api.ArtifactsService.BundleFirmware(my_request_proto)

  The stub will perform some validation and then call the build API command.
  """

  def initialize(self) -> None:
    """Expose all client stubs defined in this module."""
    stubs = Stub.__subclasses__()
    for stub in stubs:
      setattr(self, stub.__name__, stub(self))
    self._git_lock = self.m.futures.make_bounded_semaphore(1)

  def __init__(self, properties: cros_build_api_pb2.CrosBuildApiProperties,
               *args, **kwargs) -> None:
    super().__init__(*args, **kwargs)
    self._capture_stdout_stderr = properties.capture_stdout_stderr
    self._log_level = properties.log_level or 'debug'
    self._api_endpoints = None
    self._version = None
    self._publish_emerge_stats_to_bq = properties.publish_emerge_stats_to_bq
    self._publish_emerge_stats_to_prop = properties.publish_emerge_stats_to_prop
    self._parallel_operations = False
    self._git_lock = None

  @contextlib.contextmanager
  def parallel_operations(self):
    """Sets up the build API for running operations in parallel.

    Since we check out the chromite commit before making calls, parallel calls
    can clobber each other, so this context does the checkout once.
    """
    assert self._parallel_operations is False
    self._parallel_operations = True
    try:
      if ('chromeos.cros_build_api.deployable_chromite'
          in self.m.cros_infra_config.experiments):
        self.reset_checkout()
      yield
    finally:
      self._parallel_operations = False

  def reset_checkout(self):
    with self._git_lock:
      commit = self.m.file.read_text(
          'read chromite version',
          self.repo_resource('infra', 'config', 'chromite-HEAD.version'))
      with self.m.context(cwd=self.m.src_state.workspace_path /
                          chromite_location):
        try:
          self.m.git.checkout(
              commit.strip(),
              stdout=self.m.raw_io.output_text(add_output_log=True),
              stderr=self.m.raw_io.output_text(add_output_log=True))
        except self.m.step.InfraFailure as e:
          # See b/293887716 for more details about how this can occur. If the
          # checkout doesn't contain the commit we're looking for, fetch from the
          # remote and try again.
          if (e.result.stdout and
              'fatal: reference is not a tree:' in e.result.stdout) or (
                  e.result.stderr and
                  'fatal: reference is not a tree:' in e.result.stderr):
            with self.m.step.nest('fast-forwarding git checkout'):
              self.m.git.fetch()
              self.m.git.checkout(commit.strip())
          else:
            raise e

  @property
  def log_level(self) -> str:
    """Return the log level used when calling Build API."""
    return self._log_level

  @property
  def _endpoints(self) -> List[str]:
    """Return the list of endpoints. For internal use."""
    if not self._api_endpoints:
      # Initialize the endpoint list, if this is the first call to the Build
      # API. If we are testing, just grab the answer from test_api, rather than
      # creating the extra steps in expectations files. This should help reduce
      # the churn in expectations files.
      test_data = json_format.Parse(
          self.test_api.method_service_responses['Get'],
          meta_api.MethodGetResponse())
      response = (
          test_data if self._test_data.enabled else self.MethodService.Get(
              meta_api.MethodGetRequest()))
      self._api_endpoints = [m.method for m in response.methods]
    return self._api_endpoints

  @property
  def version(self) -> Version:
    """Return the version that this build API uses."""
    if not self._version:
      # Get the Build API version. If we are testing, just grab the answer from
      # test_api, rather than creating extra steps in the expectations files.
      # This should help reduce churn in expectations files.
      test_data = json_format.Parse(
          self.test_api.version_service_responses['Get'],
          meta_api.VersionGetResponse())
      response = (
          test_data if self._test_data.enabled else self.VersionService.Get(
              meta_api.VersionGetRequest()))
      version = response.version
      self._version = Version(version.major, version.minor, version.bug)
    return self._version

  def is_at_least_version(self, major=1, minor=0, bug=0) -> bool:
    """Return whether the Build API version is at least major.minor.bug."""
    return self.version >= Version(major, minor, bug)

  def GetVersion(self, test_data=None) -> Version:
    """Get the Build API version.

    The version is always queried, and the result cached.

    Args:
      test_data: A string representation of a VersionGetResponse dict.

    Returns:
      The version of the Build API.
    """
    if (self._test_data.enabled and
        not self._test_data.get('call_version_service', False)):
      test_data = json_format.Parse(test_data or '{}',
                                    meta_api.VersionGetResponse()).version
      version = test_data or self.version
    else:
      version = self('chromite.api.VersionService/Get',
                     meta_api.VersionGetRequest(),
                     meta_api.VersionGetResponse.DESCRIPTOR, infra_step=True,
                     test_output_data=test_data).version
    self._version = Version(version.major, version.minor, version.bug)
    return self._version

  def failed_pkg_logs(self, input_proto: message.Message,
                      output_proto: message.Message) -> List[Tuple[str, str]]:
    """Function to cat log file and retrieve package name.

    To use this, pass pkg_logs_lambda=api.cros_build_api.failed_pkg_logs to
    the build api call.

    Args:
      input_proto: A Request object that contains a chromiumos.Chroot attribute
        called 'chroot'.
      output_proto: A Response object that has a 'failed_package_data'
        attribute.

    Returns:
      A list of tuples (package_name, build_log).
    """
    logs = []
    for failed_pkg in output_proto.failed_package_data:
      content = ''
      with self.m.failures.ignore_exceptions():
        if failed_pkg.log_path.path:
          name = '%s/%s' % (failed_pkg.name.category,
                            failed_pkg.name.package_name)
          # Prior to R118, build API would return inside-chroot paths, so we
          # translate them here.
          # TODO(b/265885353): Remove INSIDE handling once old branches are dead.
          if failed_pkg.log_path.location == common_pb2.Path.INSIDE:
            log_path = '%s%s' % (input_proto.chroot.path,
                                 failed_pkg.log_path.path)
          else:
            log_path = failed_pkg.log_path.path

          content = self.m.file.read_raw('read log for %s' % name, log_path,
                                         'test data for %s log file' % name)
      logs.append((failed_pkg.name, content))
    return logs

  @staticmethod
  def failed_pkg_data_names(output_proto: message.Message) -> str:
    """Function to append a list of failed package to the failure step.

    To use this, pass response_lambda=api.cros_build_api.failed_pkg_data_names
    to the build api call.

    Args:
      output_proto: A Response object that has a 'failed_package_data'
          attribute.

    Returns:
      A string to append to the response step name.
    """
    # sort package names, join them with ',', and limit to 50 chars.
    failed_packages = ','.join(
        sorted(p.name.package_name for p in output_proto.failed_package_data))

    # Add to the default response step name like: ": package1,package2"
    # If it's extremely long add elipsis and a fancy sha to make unique.
    if len(failed_packages) > 50:
      fp_sha = hashlib.sha256()
      fp_sha.update(str(failed_packages).encode('utf-8'))
      failed_packages = (
          failed_packages[:50] + ('...(%s)' % fp_sha.hexdigest()[0:4]))
    if failed_packages:
      failed_packages = ': ' + failed_packages
    return failed_packages

  @staticmethod
  def failed_pkg_names(output_proto: message.Message) -> str:
    """Function to append a list of failed package to the failure step.

    To use this, pass response_lambda=api.cros_build_api.failed_pkg_names to the
    build api call.

    Args:
      output_proto: A Response object that has a 'failed_packages' attribute.

    Returns:
      A string to append to the response step name.
    """
    # sort package names, join them with ',', and limit to 50 chars.
    failed_packages = ','.join(
        sorted(p.package_name for p in output_proto.failed_packages))

    # Add to the default response step name like: ": package1,package2"
    # If it's extremely long add elipsis and a fancy sha to make unique.
    if len(failed_packages) > 50:
      fp_sha = hashlib.sha256()
      fp_sha.update(str(failed_packages).encode('utf-8'))
      failed_packages = (
          failed_packages[:50] + ('...(%s)' % fp_sha.hexdigest()[0:4]))
    if failed_packages:
      failed_packages = ': ' + failed_packages
    return failed_packages

  def __call__(
      self, endpoint: str, input_proto: message.Message,
      output_type: descriptor.Descriptor,
      test_output_data: Optional[str] = None,
      test_teelog_data: Optional[str] = None, name: Optional[str] = None,
      infra_step: bool = False, timeout: Optional[int] = None,
      response_lambda: Optional[Callable[[message.Message], str]] = None,
      pkg_logs_lambda: Optional[Callable[[message.Message, message.Message],
                                         Tuple[str, str]]] = None,
      step_text: Optional[str] = None,
      retcode_fn: Optional[Callable[[int], None]] = None) -> message.Message:
    """Call the build API with the given input proto.

    This function tries to be as dumb as possible. It does not validate that
    the endpoint exists, nor that the input_proto has the correct type. While
    clients may call this function directly, they should ALMOST ALWAYS call
    the build API through the appropriate stub.

    Args:
      endpoint: The full endpoint to call, e.g. chromite.api.MyService/MyMethod.
      input_proto: The input proto object.
      output_type: The output proto type.
      test_output_data: String of JSON to use as a response during testing.
      test_teelog_data: Text to use as tee-log contents during testing.
      name: Name for the step. Generated automatically if not specified.
      infra_step: Whether this build API call should be treated as an
        infrastructure step.
      timeout: Timeout in seconds to be supplied to the Build API call.
      response_lambda: A function that appends a string to the build API
        response step. Used to make failure step names unique across differing
        root causes.
      pkg_logs_lambda: A function to produce log information about failed
        packages. It should take two arguments: the request message and the
        response message. It should return a list of tuples (failed_package,
        logs), where failed_package is the category-package for a package that
        failed, and logs is the corresponding build logs contents.
      step_text: text to put on the step for the call.
      retcode_fn: Called with the return code from Build API. This is useful for
        when the return code is 2 (RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE).

    Returns:
      The parsed response proto.
    """
    # Fetch the endpoint list on the first call, rather than first call to
    # has_endpoint. This should reduce the expectations churn as has_endpoint
    # calls are added.  Avoid recusion though.
    if (not self._api_endpoints and
        endpoint != 'chromite.api.MethodService/Get'):
      _ = self._endpoints

    response_lambda = response_lambda or (lambda op: '')
    pkg_logs_lambda = pkg_logs_lambda or (lambda *args: [])
    retcode_fn = retcode_fn or (lambda retcode: None)

    with self.m.step.nest(name or 'call %s' % endpoint) as presentation:
      if step_text:
        presentation.step_text = step_text

      messages_path = self.m.path.mkdtemp(prefix='build_api_messages')
      input_path = messages_path / 'input_proto.json'
      output_path = messages_path / 'output_proto.json'
      logfile_path = messages_path / 'build_log.txt'

      # Write the input proto JSON to a temp file (which is how it's passed to
      # the build API) and record it to the step logs for debugging.
      input_json = json_format.MessageToJson(input_proto,
                                             use_integers_for_enums=True)
      self.m.file.write_raw('write input file', input_path, input_json)
      presentation.logs['request'] = input_json
      presentation.logs['response'] = '{}'

      cmd = []
      if self._capture_stdout_stderr:
        tee_script = self.repo_resource('recipe_scripts/tee_wrapper.sh')
        # Make the tee_script and logfile path be the first arguments.
        # The tee_script will execute the arguments after logfile path and
        # tee the output into the logfile path.
        cmd.append(str(tee_script))
        cmd.append(logfile_path)

      # Make sure the chromite checkout is at the right version.
      # We do this before every call because there is no guarantee that another
      # line of code doesn't redo the manifest checkout and blow away our set
      # version.
      if ('chromeos.cros_build_api.deployable_chromite'
          in self.m.cros_infra_config.experiments
         ) and not self._parallel_operations:
        self.reset_checkout()

      cmd.extend([
          self.m.src_state.workspace_path.joinpath(
              f'{chromite_location}/bin/build_api'), '--input-json', input_path,
          '--output-json', output_path, '--log-level', self._log_level, endpoint
      ])
      file_contents = None

      # build_api needs to invoke other chromite/bin binaries, hence this dir
      # needs to be on the PATH.
      # There is a good chance this will not work with chromite-HEAD because the
      # build-api has explicit path references. For now, rely on the fact that
      # chromite-HEAD will only be used for signing, which will never call other
      # build-api calls internally, and use chromite_location for safety.
      chromite_bin_dir = self.m.src_state.workspace_path / 'chromite/bin'
      with self.m.context(env_suffixes={'PATH': [chromite_bin_dir]}):
        try:
          output_proto = reflection.MakeClass(output_type)()
          # For Build API retcode 2 indicates that the invocation failed in some
          # way but a consumable response has been produced.
          request_time = timestamp_pb2.Timestamp()
          request_time.FromDatetime(self.m.time.utcnow())
          try:
            # Note: 0 and 2 are considered ok return values because in
            # chromite/api/controller/__init__.py, 0 is RETRN_CODE_SUCCESS and
            # 2 is RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE (meaning that
            # even though a problem occurred, there is actionable info in the
            # response.)
            call_step = self.m.step('call build API script', cmd, ok_ret=(0, 2),
                                    infra_step=infra_step, timeout=timeout)
          finally:
            response_time = timestamp_pb2.Timestamp()
            response_time.FromDatetime(self.m.time.utcnow())
            if self._capture_stdout_stderr:
              file_contents = self.m.file.read_raw('read tee output file',
                                                   logfile_path,
                                                   test_data=test_teelog_data)
              # Much of the build api calls emerge, collect stats!
              self.m.portage.publish_emerge_stats(
                  endpoint,
                  file_contents.decode('utf-8', errors='backslashreplace'),
                  publish_to_bq=self._publish_emerge_stats_to_bq,
                  set_output_prop=self._publish_emerge_stats_to_prop)
              if file_contents:
                presentation.logs['stdout'] = file_contents

          # If no test data is provided, see if we have our own.
          test_output_data = (
              test_output_data or
              self.test_api.response_for_endpoint(endpoint, self._test_data))

          # Parse the output to a proto and record it in the logs.
          output_json = self.m.file.read_raw('read output file', output_path,
                                             test_data=test_output_data)

          json_format.Parse(output_json, output_proto,
                            ignore_unknown_fields=True)

          # Since we can't rename the api step, and certain applications/tables
          # have taken them as input (e.g. sheriff-o-matic), we then make a
          # 'response' step that we can have foreknowledge of what the name
          # _should_ be based on the call's results.
          presentation.logs['response'] = json.dumps(
              json.loads(output_json), indent=2)
          resp_step_name = _response_step_name(output_proto, response_lambda)

          with self.m.step.nest(resp_step_name) as resp_pres:
            resp_pres.logs['build api stdout'] = file_contents or ''
            pkg_logs = pkg_logs_lambda(input_proto, output_proto)
            pkg_logs.sort(key=lambda pl: pl[0].package_name)
            resp_pres.logs.update({
                '%s/%s log' % (p.category, p.package_name): log_contents
                for (p, log_contents) in pkg_logs
            })
            if call_step.exc_result.retcode != 0:
              resp_pres.status = self.m.step.FAILURE

        except StepFailure as e:
          call_step = e.result
          raise e

        finally:
          with self.m.failures.ignore_exceptions():
            # Publish Build API responses on Cloud Pub/Sub if they are registered.
            if self.m.analysis_service.can_publish_event(
                input_proto, output_proto):
              self.m.analysis_service.publish_event(input_proto, output_proto,
                                                    request_time, response_time,
                                                    call_step, file_contents)

      retcode_fn(call_step.exc_result.retcode)
      return output_proto

  def has_endpoint(self, stub: 'Stub', method: str) -> bool:
    """Verifies that the given endpoint can be called.

    Args:
      stub: Stub instance to check whether `method` can be called on it.
      method: Name of method to check for.

    Returns:
      Whether `method` can be called on `stub`.
    """
    # First check that stub is really a Stub registered with the API.
    stub_name = type(stub).__name__
    if not isinstance(stub, Stub) or not getattr(self, stub_name, None) == stub:
      return False

    # Next make sure that the proto defs exist for the method.
    try:
      service_name, _ = _verify_proto_endpoint(stub, method)
    except KeyError:
      return False

    # Lastly, check that the build API side implements the endpoint, and that
    # testing has not told us to remove the endpoint.
    wanted = '%s/%s' % (service_name, method)
    remove_endpoints = {}
    if self._test_data.enabled:
      remove_endpoints = self._test_data.get('remove_endpoints', {})
    return wanted in self._endpoints and wanted not in remove_endpoints

  def new_result_path(self) -> common_pb2.ResultPath:
    """Create a ResultPath for the BAPI to extract output files into."""
    return common_pb2.ResultPath(
        path=common_pb2.Path(
            path=self.m.path.abspath(self.m.path.mkdtemp()),
            location=common_pb2.Path.Location.OUTSIDE,
        ),
    )


def _response_step_name(output_proto: message.Message,
                        create_suffix: Callable[[message.Message], str]) -> str:
  """Create the name for a response step.

  Args:
    output_proto: A build API response message.
    create_suffix: A function that creates a suffix for the step name based
      on the contents of the output message.
  """
  return 'call response%s' % create_suffix(output_proto)
