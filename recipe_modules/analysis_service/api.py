# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.analysis_service.analysis_service import AnalysisServiceEvent

from google.protobuf import json_format

from recipe_engine import recipe_api


class AnalysisServiceApi(recipe_api.RecipeApi):

  def __init__(self, pubsub_project_id, pubsub_topic_id, *args, **kwargs):
    super(AnalysisServiceApi, self).__init__(*args, **kwargs)
    self._pubsub_project_id = pubsub_project_id
    self._pubsub_topic_id = pubsub_topic_id

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

    # The type name of 'message'.
    message_type_name = message.DESCRIPTOR.full_name

    # Iterate the possible values of 'oneof_name'. Create a list of all that
    # match the type of 'message'.
    oneof_descriptor = analysis_service_event.DESCRIPTOR.oneofs_by_name[
        oneof_name]

    matching_field_descriptors = []
    for field_descriptor in oneof_descriptor.fields:
      if field_descriptor.message_type.full_name == message_type_name:
        matching_field_descriptors.append(field_descriptor)

    # Check there is exactly one value of 'oneof_name' that has the same type
    # as 'message'.
    if len(matching_field_descriptors) != 1:
      raise ValueError(
          'Expected exactly one type in {} to be of type {}. Found {}.'.format(
              oneof_name, message_type_name, len(matching_field_descriptors)))

    # Copy 'message' onto 'analysis_service_event'.
    field_descriptor = matching_field_descriptors[0]
    getattr(analysis_service_event, field_descriptor.name).CopyFrom(message)

    # Check 'oneof_name' is now set.
    assert analysis_service_event.WhichOneof(
        oneof_name) is not None, 'Expected {} to be set.'.format(oneof_name)

  def publish_event(self, request, response):
    """Publish request and response on Cloud Pub/Sub.

    Wraps request and response in a AnalysisServiceEvent. If request's type is
    not found exactly once in the AnalysisServiceEvent 'request' oneof, an
    assertion is thrown (similar for response).

    Does not check that request and response are corresponding types, e.g. it is
    possible to send a InstallPackagesRequest and SysrootCreateResponse; it is
    up to the caller to not do this.

    Args:
      request (proto in AnalysisServiceEvent 'request' oneof): The request to
        log
      response (proto in AnalysisServiceEvent 'response' oneof): The response to
        log
    """
    with self.m.step.nest('publish event') as step:
      analysis_service_event = AnalysisServiceEvent()
      self._set_oneof_by_matching_type(analysis_service_event,
                                       oneof_name='request', message=request)
      self._set_oneof_by_matching_type(analysis_service_event,
                                       oneof_name='response', message=response)

      step.presentation.logs['published event'] = [
          json_format.MessageToJson(analysis_service_event,
                                    including_default_value_fields=True)
      ]

      self.m.cloud_pubsub.publish_message(
          self._pubsub_project_id, self._pubsub_topic_id,
          analysis_service_event.SerializeToString())
