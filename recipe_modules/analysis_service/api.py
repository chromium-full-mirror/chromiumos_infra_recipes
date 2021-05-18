# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.analysis_service.analysis_service import AnalysisServiceEvent

from google.protobuf import json_format

from recipe_engine import recipe_api


def _truncate_output(full_output, max_output_bytes):
  """Truncate full_output if needed for sending/storing/querying.

  When truncating full_output, the last |max_output_bytes| are kept rather
  than the first.

  Args:
    full_output (str): The full output captured from a step.
    max_output_bytes (int): Max number of bytes in returned string.
  Return:
    A tuple of truncated string, bytes removed.
  """
  # In python2, len returns the number of bytes needed to represent a string.
  # See recipe_modules/analysis_service/examples/full.py
  # api.test('basic-nonascii') for an example of non-ascii characters.
  output_length = len(full_output)
  if output_length <= max_output_bytes:
    return full_output, 0
  return full_output[-max_output_bytes:], output_length - max_output_bytes


def _set_step_execution_result_fields(analysis_service_event, step_data):
  """Set the StepExecutionResult fields on an AnalysisServiceEvent.

  Args:
    analysis_sevice_event (AnalysisServiceEvent): The AnalysisServiceEvent to be
      modified
    step_data (recipe_engine.StepData): Data from the step being logged.
  """
  src = step_data.exc_result
  dst = analysis_service_event.step_execution_result

  if src.retcode:
    dst.retcode = src.retcode

  if src.had_exception:  # pragma: nocover, no way to simulate "had_exception" in tests.
    dst.had_exception = src.had_exception

  if src.had_timeout:
    dst.had_timeout = src.had_timeout

  if src.was_cancelled:  # pragma: nocover, no way to simulate "was_cancelled" in tests.
    dst.was_cancelled = src.was_cancelled


# TODO(crbug.com/964444): Rename to cros_analysis_service.
class AnalysisServiceApi(recipe_api.RecipeApi):

  def __init__(self, properties, *args, **kwargs):
    super(AnalysisServiceApi, self).__init__(*args, **kwargs)
    self._pubsub_project_id = properties.pubsub_project_id or "chromeos-bot"
    self._pubsub_topic_id = (
        properties.pubsub_topic_id or "analysis-service-events")
    self._max_stdout_stderr_bytes = properties.max_stdout_stderr_bytes

  def _get_field_name_by_matching_type(self, oneof_name, message):
    """Get the field on AnalysisServiceEvent for 'oneof_name' and 'message'.

    Args:
      oneof_name (str): The name of a oneof on 'analysis_service_event'.
      message (proto in an AnalysisServiceEvent oneof): The proto that will be
        copied to 'analysis_service_event'.

    For example, if 'oneof_name' is request, and 'message' is of type,
    InstallPackagesRequest, the returned field name will be
    'install_packages_request'.

    Return:
      A str if there is a matching field, None otherwise.
    """
    # The type name of 'message'.
    message_type_name = message.DESCRIPTOR.full_name

    # Iterate the possible values of 'oneof_name'. Create a list of all that
    # match the type of 'message'.
    oneof_descriptor = AnalysisServiceEvent(
    ).DESCRIPTOR.oneofs_by_name[oneof_name]

    matching_field_descriptors = []
    for field_descriptor in oneof_descriptor.fields:
      if field_descriptor.message_type.full_name == message_type_name:
        matching_field_descriptors.append(field_descriptor)

    # Check there is no more than one value of 'oneof_name' that has the same
    # type as 'message'.
    assert len(matching_field_descriptors) <= 1, (
        'Expected exactly no more than one type in {} to be of type {}. '
        'Found {}.').format(oneof_name, message_type_name,
                            len(matching_field_descriptors))

    return (matching_field_descriptors[0].name
            if matching_field_descriptors else None)

  def _set_oneof_by_matching_type(self, analysis_service_event, oneof_name,
                                  message):
    """Set the appropriate oneof by searching on type.

    Args:
      analysis_service_event (AnalysisServiceEvent): The proto that will be
        mutated.
      oneof_name (str): The name of a oneof on 'analysis_service_event'.
      message (proto in an AnalysisServiceEvent oneof): The proto that will be
        copied to 'analysis_service_event'.

    An example:

    ```
    analysis_service_event = AnalysisServiceEvent()
    assert analysis_service_event.WhichOneof('request') is None

    install_packages_request = InstallPackagesRequest()

    _set_oneof_by_matching_type(
      analysis_service_event, 'request', install_packages_request
    )

    # analysis_service_event.install_packages_request should now be set, because
    # it has the same type as the InstallPackagesRequest we constructed.
    assert analysis_service_event.WhichOneof(
      'request') == 'install_packages_request'
    ```
    """
    # Check the oneof isn't already set.
    assert analysis_service_event.WhichOneof(
        oneof_name) is None, '{} is already set.'.format(oneof_name)

    matching_field_name = self._get_field_name_by_matching_type(
        oneof_name, message)

    # Callers should check can_publish_event, so there must be a returned
    # field name.
    assert matching_field_name

    # It is possible for the Python types of 'analysis_service_event.<field>'
    # and 'message' to be different, even if they represent types that should
    # be able to be copied to each other. For example,
    # 'chromite.api.sysroot_pb2.InstallPackagesResponse' and
    # 'google.protobuf.internal.python_message.InstallPackagesResponse'. In
    # order to avoid this case, use 'ParseFromString' and 'SerializeToString'.
    #
    # TODO(crbug.com/967721): Directly copy once type mismatch is fixed.
    getattr(analysis_service_event,
            matching_field_name).ParseFromString(message.SerializeToString())

    # Check 'oneof_name' is now set.
    assert analysis_service_event.WhichOneof(
        oneof_name) is not None, 'Expected {} to be set.'.format(oneof_name)

  def _set_step_output(self, analysis_service_event, step_output):
    """Set the step_data to store stdout and stderr information.

    Args:
      analysis_sevice_event (AnalysisServiceEvent): The AnalysisServiceEvent to
        be modified.
      step_output (str): Log output of the step being logged.
    """
    step = self.m.step.active_result
    if step_output:
      truncated_stdout, bytes_removed = _truncate_output(
          step_output, self._max_stdout_stderr_bytes)
      analysis_service_event.stdout = truncated_stdout
      if bytes_removed == 0:
        step.presentation.logs['stdout_truncation'] = [
            'Full step output is {} bytes, no truncation'.format(
                len(step_output))
        ]
      else:
        step.presentation.logs['stdout_truncation'] = [
            'Full step output is {} bytes, truncated to {} bytes'.format(
                len(step_output), self._max_stdout_stderr_bytes)
        ]

  def can_publish_event(self, request, response):
    """Return whether 'request' and 'response' can be published.

    Based on whether the types are both part of AnalysisServiceEvent. For
    example,
    `can_publish_event(InstallPackagesRequest(), InstallPackagesResponse())` is
    true because the AnalysisServiceEvent contains these fields.

    `can_publish_event(NewRequest(), NewResponse())` would not be true, because
    those fields are not added to AnalysisServiceEvent.

    Args:
      request (proto in AnalysisServiceEvent 'request' oneof): The request to
        log
      response (proto in AnalysisServiceEvent 'response' oneof): The response to
        log

    Return:
      bool
    """
    return self._get_field_name_by_matching_type(
        'request', request) and self._get_field_name_by_matching_type(
            'response', response)

  def publish_event(self, request, response, request_time, response_time,
                    step_data, step_output=None):
    """Publish request and response on Cloud Pub/Sub.

    Wraps request and response in a AnalysisServiceEvent. 'can_publish_event'
    must be called before (and return true).

    Does not check that request and response are corresponding types, e.g. it is
    possible to send a InstallPackagesRequest and SysrootCreateResponse; it is
    up to the caller to not do this.

    Args:
      request (proto in AnalysisServiceEvent 'request' oneof): The request to
        log
      response (proto in AnalysisServiceEvent 'response' oneof): The response to
        log
      request_time (google.protobuf.timestamp_pb2.Timestamp): The time the
        request was sent by the caller.
      response_time (google.protobuf.timestamp_pb2.Timestamp): The time the
        response was received by the caller.
      step_data (recipe_engine.StepData): Data from the step that sent the request.
      step_output (str): Output for the step.
    """
    with self.m.step.nest('publish event') as presentation:
      if not self.can_publish_event(request, response):
        raise ValueError(
            'Must check can_publish_event before calling publish_event.')

      analysis_service_event = AnalysisServiceEvent()

      analysis_service_event.build_id = self.m.buildbucket.build.id
      analysis_service_event.step_name = step_data.name
      if self._max_stdout_stderr_bytes > 0 and step_output:
        self._set_step_output(analysis_service_event, step_output)

      _set_step_execution_result_fields(analysis_service_event, step_data)

      self._set_oneof_by_matching_type(analysis_service_event,
                                       oneof_name='request', message=request)
      self._set_oneof_by_matching_type(analysis_service_event,
                                       oneof_name='response', message=response)

      if request_time.ToNanoseconds() > response_time.ToNanoseconds():
        raise ValueError(
            'Request time ({}) cannot be after response time ({}).'.format(
                request_time, response_time))

      analysis_service_event.request_time.CopyFrom(request_time)
      analysis_service_event.response_time.CopyFrom(response_time)

      presentation.logs['published event'] = [
          json_format.MessageToJson(analysis_service_event)
      ]

      # Data is passed to the publish-message support binary via JSON. The
      # serialized proto must be base64 encoded to prevent UnicodeDecodeErrors.
      # It will be unencoded by the publish-message support binary before it
      # is published.
      self.m.cloud_pubsub.publish_message(
          self._pubsub_project_id, self._pubsub_topic_id,
          analysis_service_event.SerializeToString().encode('base64'))
