# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Contains functions for building and sending build status to a pub/sub topic.

The messages for build reporting are defined in:
  infra/proto/src/chromiumos/build_report.proto

And are specifically designed to be aggregated as a build progresses to create
the current status.  This means we can focus on sending out just the status
pieces that we need without worrying about maintaining the state of the entire
message.

The pub/sub topic to send status to is configurable through the `pubsub_project`
and `pubsub_topic` properties for the module.  If not set, these default to
`chromeos-build-reporting` and `chromeos-builds-all`, which is intended to be
the unfiltered top-level topic for all builds.
"""

import contextlib
import functools
import types

from google.protobuf.json_format import MessageToJson
from google.protobuf.timestamp_pb2 import Timestamp

# infra/proto/src/chromiumos/builder_report.proto
from PB.chromiumos.build_report import BuildReportBeta as BuildReport

from recipe_engine import recipe_api
from recipe_engine.recipe_api import InfraFailure, StepFailure


def default_project(staging):
  """Default cloud project containing the pubsub topic to send to."""
  if staging:
    return 'chromeos-build-reporting-dev'
  return 'chromeos-build-reporting'


def default_topic(staging):
  """Default pubsub topic to send updates to."""
  return 'chromeos-builds-all'


class _MessageDelegate:
  """
  MessageDelegate wraps a protobuf message, adding a publish() function.

  We're not allowed to inherit from protos and can't add attributes to them
  either, so this is meant to allow us to return an object that can be
  manipulated like a regular proto and then call the publish() method to send to
  pub/sub.
  """

  def __init__(self, msg, send_func):
    """Take a message to wrap and a send function to call to publish it."""
    self._msg = msg
    self._send_func = send_func

  # Pass attribute requests to underlying message.  This is only called when
  # the attribute doesn't exist in __dict__, so we don't have to explicitly
  # check whether a function is overloaded or not.
  def __getattr__(self, attr):
    return getattr(self._msg, attr)

  def publish(self):
    self._send_func()
    return self


class BuildReportingApi(recipe_api.RecipeApi):
  """API implemention for build reporting."""

  # More convenient access to very common constants.
  STEP_SUCCESS = BuildReport.StepDetails.STATUS_SUCCESS
  STEP_FAILURE = BuildReport.StepDetails.STATUS_FAILURE
  STEP_RUNNING = BuildReport.StepDetails.STATUS_RUNNING
  STEP_INFRA_FAILURE = BuildReport.StepDetails.STATUS_INFRA_FAILURE

  @staticmethod
  def step_as_str(step_name):
    """Convert a BuildReport.StepDetails.StepName to a canonical string."""
    return BuildReport.StepDetails.StepName.Name(step_name)

  # property accessors
  @property
  def pubsub_project(self):
    return self._pubsub_project or default_project(self.m.build_menu.is_staging)

  @property
  def pubsub_topic(self):
    return self._pubsub_topic or default_topic(self.m.build_menu.is_staging)

  @property
  def build_type(self):
    return self._build_type

  @property
  def merged_build_report(self):
    return self._build_report

  def set_build_type(self, build_type):
    """Set the type for the build, must be set once and only once."""
    if not build_type in BuildReport.BuildType.values():
      raise ValueError("Invalid build type '%d', must be value defined in "
                       "BuildReport.BuildType" % build_type)
    if self._build_type is not None:
      raise RuntimeError("Build type can only be set once.")

    self._build_type = build_type

  def _MakeBuildReport(self):
    """Create new instance of BuildReport with id and possibly populated."""
    build_report = BuildReport()
    build_report.buildbucket_id = self.m.buildbucket.build.id
    return build_report

  def __init__(self, properties, *args, **kwargs):
    super(BuildReportingApi, self).__init__(*args, **kwargs)
    self._properties = properties
    self._pubsub_project = properties.pubsub_project
    self._pubsub_topic = properties.pubsub_topic
    self._build_type = None
    self._build_type_sent = False
    self._build_report = BuildReport()
    self._step_order = 0

  def publish(self, build_report):
    """Send a BuildReport to the pubsub topic.

    Also aggregates the published BuildReport which is then available through
    the merged_build_report property.

    Args:
      build_report: Instance of BuildReport to send to pub/sub

    Return:
      Reference to input message
    """
    if not isinstance(build_report, BuildReport):
      raise TypeError("Can only publish BuildReport messages.")

    # If we haven't send the build type, add it when it becomes available.
    if not self._build_type_sent:
      if self._build_type is None:
        raise RuntimeError(
            "Build type must be set before sending first message.")
      build_report.type = self._build_type
      self._build_type_sent = True

    with self.m.step.nest('build status pubsub update') as pres:
      pres.logs['message'] = MessageToJson(build_report)
      self.m.cloud_pubsub.publish_message(
          self.pubsub_project,
          self.pubsub_topic,
          # The publish-message binary requires that messages be base64 encoded to
          # avoid issues with binary data and strings.
          build_report.SerializeToString().encode('base64'),
      )

    # Aggregate sent messages so we have a copy of the final status on our side.
    self._build_report.MergeFrom(build_report)

    return build_report

  def create_build_report(self):
    """Create BuildReport instance that can be .published().

    Return:
      _MessageDelegate wrapping BuildReport instance
    """
    build_report = self._MakeBuildReport()
    return _MessageDelegate(
        build_report,
        lambda: self.publish(build_report),
    )

  def create_build_config(self):
    """Create a BuildConfig instance that can be .published().

    Return:
       _MessageDelegate wrapping BuildConfig instance
    """
    build_report = self._MakeBuildReport()
    return _MessageDelegate(
        build_report.config,
        lambda: self.publish(build_report),
    )

  def publish_status(self, status):
    """Publish build status."""
    build_status = BuildReport.BuildStatus()
    build_status.value = status
    build_report = self._MakeBuildReport()
    build_report.status.CopyFrom(build_status)
    self.publish(build_report)

  def publish_build_artifact(
      self,
      artifact_type,
      gs_uri,
      sha256,
      created=None,
  ):
    """Publish information about a created artifact.

    Args:
      artifact_type: BuildReport.BuildArtifact.Type for artifact
      gs_uri: GS bucket URI for artifact (eg: gs://foo/bar/baz.tgz)
      sha256: SHA256 hash for artifact
      created (optional): datetime for when artifact was created (default: now)

    Throws:
      ValueError if gs_uri isn't properly formatted with gs:// prefix

    Return:
      Nothing
    """
    created = created or self.m.time.utcnow()

    if not gs_uri.startswith("gs://"):
      raise ValueError("GS bucket URI should start with gs:// prefix")

    build_report = self._MakeBuildReport()
    artifact = build_report.artifacts.add()

    artifact.type = artifact_type
    artifact.uri.gcs = gs_uri
    artifact.sha256 = sha256
    artifact.created.FromDatetime(created)

    self.publish(build_report)

  def create_step_info(
      self,
      step_name,
      start_time=None,
      end_time=None,
      status=BuildReport.StepDetails.STATUS_RUNNING,
  ):
    """Create a StepDetails instance to publish information for a step.

    Args:
      step_name: Predefined step name, one of BuildReport.StepDetails.StepName
      start_time: UTC datemite indicating step start time
      end_time: UTC datetime indicating step end time
      status: Step status (default: running)

    Return:
       _MessageDelegate wrapping StepDetails instance
    """
    build_report = self._MakeBuildReport()

    step_details = build_report.steps.info[self.step_as_str(step_name)]
    step_details.order = self._step_order
    step_details.status = status

    if start_time:
      step_details.runtime.begin.FromDatetime(start_time)

    if end_time:
      step_details.runtime.end.FromDatetime(end_time)

    # Increment step order counter so that steps are in the order that this
    # function was called.
    self._step_order += 1

    return _MessageDelegate(
        step_details,
        lambda: self.publish(build_report),
    )

  @contextlib.contextmanager
  def step_reporting(self, step_name):
    """Create a context manager to automatically send out step status.

    When created, initial step status is published with the current time and
    a status of STATUS_RUNNING.

    When the context is exited, the step endtime is set and status is set to
    STATUS_SUCCESS by default.

    A handle is returned from the context manager which can be used to set
    the return status to STATUS_FAILURE or STATUS_INFRA_FAILURE via the
    fail() and infra_fail() methods respectively.

    If a StepFailure occurs, status is set to STATUS_FAILURE automatically, and
    similarly, InfraFailure sets status to STATUS_INFRA_FAILURE.

    Args:
      step_name: Predefined step name, one of BuildReport.StepDetails.StepName

    Return:
      Handle which can be used to set the step status manually.
    """

    # Workaround for not having nonlocal in Python 2.  This lets us mutate the
    # status value in the handle closures below because we're not rebinding
    # notlocal (which is the actual variable closed over).
    class notlocal:
      status = self.STEP_SUCCESS

    class handle:

      @staticmethod
      def fail():
        notlocal.status = self.STEP_FAILURE

      @staticmethod
      def infra_fail():
        notlocal.status = self.STEP_INFRA_FAILURE

    # Publish the initial step status.
    step_info = self.create_step_info(
        step_name,
        start_time=self.m.time.utcnow(),
    )
    step_info.publish()

    try:
      yield handle
    except InfraFailure:
      handle.infra_fail()
      raise
    except StepFailure:
      handle.fail()
      raise
    finally:
      # Publish the final step time.
      step_info.runtime.end.FromDatetime(self.m.time.utcnow())
      step_info.status = notlocal.status
      step_info.publish()
