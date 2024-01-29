# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for publishing events to the Analysis Service."""

import base64
from typing import Optional, Tuple, Union, Iterable

from google.protobuf import json_format
from google.protobuf.message import Message
from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.timestamp_pb2 import Timestamp

from PB.analysis_service.analysis_service import AnalysisServiceEvent
import PB.chromiumos.common as common_pb2
from PB.recipe_modules.chromeos.analysis_service.analysis_service import AnalysisServiceProperties
from recipe_engine import recipe_api
from recipe_engine.step_data import StepData


# Max bytes to include from stdout/stderr of each step as part of the event.
# This limit applies to stdout and stderr individually. A step may include up to
# this many bytes for each one.
_MAX_STDOUT_STDERR_BYTES = 1000000  # 1MB


def _truncate_output(full_output: Union[str, bytes],
                     max_output_bytes: int) -> Tuple[str, int]:
  """Truncate full_output if needed for sending/storing/querying.

  When truncating full_output, the last |max_output_bytes| are kept rather
  than the first.

  Args:
    full_output: The full output captured from a step.
    max_output_bytes: Max number of bytes in returned string.

  Return:
    A tuple of (truncated_string, removed), where truncated_string is the
    modified string, and removed is the number of bytes removed.
  """
  # Some callers are still passing in bytes, so coerce the input to a string.
  # We use UTF-32 to make all characters 4 bytes wide while we are manipulating
  # the string.
  full_string = str(full_output).encode('utf-32')
  # Divide by 4, as we have 4-byte wide characters, but remove an extra 1 as
  # UTF-32 has a '\xff\xfe\x00\x00' prefix on the string.
  len_in_chars = len(full_string) / 4 - 1
  if len_in_chars > max_output_bytes:
    removed = len_in_chars - max_output_bytes
    # We need to keep the first 4 bytes, as they are the UTF-32 prefix.
    truncated_string = (full_string[:4] + full_string[-max_output_bytes * 4:])
  else:
    truncated_string = full_string
    removed = 0
  return truncated_string.decode('utf-32'), removed


def _set_step_execution_result_fields(
    analysis_service_event: AnalysisServiceEvent, step_data: StepData):
  """Set the StepExecutionResult fields on an AnalysisServiceEvent.

  Args:
    analysis_sevice_event: The AnalysisServiceEvent to be modified.
    step_data: Data from the step being logged.
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


class AnalysisServiceApi(recipe_api.RecipeApi):

  def __init__(self, properties: AnalysisServiceProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._pubsub_project_id = properties.pubsub_project_id or 'chromeos-bot'
    self._pubsub_topic_id = (
        properties.pubsub_topic_id or 'analysis-service-events')

  def _logging_optional(self, field_desc: FieldDescriptor) -> bool:
    if self._test_data.enabled:
      return field_desc.full_name == self._test_data.get(
          'optional_field_name', '')
    return field_desc.GetOptions().Extensions[
        common_pb2.logging_optional]  # pragma: nocover

  def _process_field(self, field_desc: FieldDescriptor, field: Message) -> bool:
    found_optional = False
    if self._logging_optional(field_desc):
      if isinstance(field, Iterable):
        del field[:]
      else:
        field.Clear()
      found_optional = True

    field_set = field_desc.message_type.fields if field_desc.message_type else []
    for f in field_set:
      if isinstance(field, Iterable):
        for m in field:
          found_optional |= self._process_field(f, getattr(m, f.name))
      else:
        found_optional |= self._process_field(f, getattr(field, f.name))
    return found_optional

  def _clear_logging_optional(self, message: Message) -> bool:
    found_optional = False
    for f in message.DESCRIPTOR.fields:
      found_optional |= self._process_field(f, getattr(message, f.name))
    return found_optional

  def _filter_payload(self, analysis_service_event: AnalysisServiceEvent):
    """Remove proto fields that are marked as logging_optional.

    Args:
      analysis_service_event: The proto that will be processed
    """
    found_optional = False
    step = self.m.step.active_result
    response_type = analysis_service_event.WhichOneof('response')
    response_message = getattr(analysis_service_event, response_type)
    found_optional = self._clear_logging_optional(response_message)
    step.presentation.logs['payload_truncation'] = 'Payload %s filtered' % (
        'was' if found_optional else 'not')

  @staticmethod
  def _set_oneof_by_matching_type(analysis_service_event: AnalysisServiceEvent,
                                  oneof_name: str, message: Message):
    """Set the appropriate oneof by searching on type.

    Args:
      analysis_service_event: The proto that will be mutated.
      oneof_name: The name of a oneof on 'analysis_service_event'.
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

    matching_field_name = _get_field_name_by_matching_type(oneof_name, message)

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

  def _set_step_output(
      self,
      analysis_service_event: AnalysisServiceEvent,
      step_output: str,
      max_stdout_stderr_bytes: int = _MAX_STDOUT_STDERR_BYTES,
  ) -> None:
    """Set the step_data to store stdout and stderr information.

    Args:
      analysis_service_event: The AnalysisServiceEvent to be modified.
      step_output: Log output of the step being logged.
      max_stdout_stderr_bytes: Truncate stdout and stderr to this many bytes.
    """
    step = self.m.step.active_result
    if step_output:
      truncated_stdout, bytes_removed = _truncate_output(
          step_output, max_stdout_stderr_bytes)
      analysis_service_event.stdout = truncated_stdout
      if bytes_removed == 0:
        step.presentation.logs['stdout_truncation'] = (
            f'Full step output is {len(step_output)} bytes, no truncation')
      else:
        step.presentation.logs['stdout_truncation'] = (
            f'Full step output is {len(step_output)} bytes, '
            f'truncated to {max_stdout_stderr_bytes} bytes')

  @staticmethod
  def can_publish_event(request: Message, response: Message) -> bool:
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
      Whether an event can be published.
    """
    return (_get_field_name_by_matching_type('request', request) and
            _get_field_name_by_matching_type('response', response))

  def publish_event(
      self, request: Message, response: Message, request_time: Timestamp,
      response_time: Timestamp, step_data: StepData,
      step_output: Optional[str] = None,
      max_stdout_stderr_bytes: int = _MAX_STDOUT_STDERR_BYTES) -> None:
    """Publish request and response on Cloud Pub/Sub.

    Wraps request and response in a AnalysisServiceEvent. 'can_publish_event'
    must be called before (and return true).

    Does not check that request and response are corresponding types, e.g. it is
    possible to send a InstallPackagesRequest and SysrootCreateResponse; it is
    up to the caller to not do this.

    Args:
      request (proto in AnalysisServiceEvent 'request' oneof): The request to
        log.
      response (proto in AnalysisServiceEvent 'response' oneof): The response to
        log.
      request_time: The time the request was sent by the caller.
      response_time: The time the response was received by the caller.
      step_data: Data from the step that sent the request.
      step_output: Output for the step.
      max_stdout_stderr_bytes: Truncate stdout and stderr to this many bytes.
    """
    with self.m.step.nest('publish event') as presentation:
      if not self.can_publish_event(request, response):
        raise ValueError(
            'Must check can_publish_event before calling publish_event.')

      analysis_service_event = AnalysisServiceEvent()

      analysis_service_event.build_id = self.m.buildbucket.build.id
      analysis_service_event.step_name = step_data.name
      if step_output:
        self._set_step_output(analysis_service_event, step_output,
                              max_stdout_stderr_bytes=max_stdout_stderr_bytes)

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
      # For special cases, reduce the amount of data in the payload
      self._filter_payload(analysis_service_event)

      presentation.logs['published event'] = json_format.MessageToJson(
          analysis_service_event)

      # Data is passed to the publish-message support binary via JSON. The
      # serialized proto must be base64 encoded to prevent UnicodeDecodeErrors.
      # It will be unencoded by the publish-message support binary before it
      # is published.
      event_serialized = analysis_service_event.SerializeToString()
      event_b64 = base64.b64encode(event_serialized).decode()
      self.m.cloud_pubsub.publish_message(self._pubsub_project_id,
                                          self._pubsub_topic_id, event_b64)


def _get_field_name_by_matching_type(oneof_name: str,
                                     message: Message) -> Optional[str]:
  """Get the field on AnalysisServiceEvent for 'oneof_name' and 'message'.

  Args:
    oneof_name: The name of a oneof on 'analysis_service_event'.
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
