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

import base64
import contextlib
import json
import six

from google.protobuf.json_format import MessageToDict

from RECIPE_MODULES.chromeos.build_reporting import build_report_proto_helpers as helpers

# infra/proto/src/chromiumos/builder_report.proto
from PB.chromiumos.build_report import BuildReportBeta as BuildReport

from recipe_engine import recipe_api
from recipe_engine.recipe_api import InfraFailure, StepFailure

# TODO(b/200713946): Lookup the builder region and use that endpoint
PUBSUB_ENDPOINT = "us-central1-pubsub.googleapis.com:443"

BuildConfig = BuildReport.BuildConfig


def default_project(staging):
  """Default cloud project containing the pubsub topic to send to."""
  if staging:
    return 'chromeos-build-reporting-dev'
  return 'chromeos-build-reporting'


def default_topic():
  """Default pubsub topic to send updates to."""
  return 'chromeos-builds-all'


def make_oneup():
  """Construct a oneup counter function."""

  def closure():
    closure.counter += 1
    return closure.counter

  closure.counter = 0
  return closure


class _MessageDelegate(object):
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

  # Set attribute requests to the underlying message. This essentially creates
  # an allowlist of attributes set in the _MessageDelegate instances.
  def __setattr__(self, attr, value):
    if attr in ['_msg', '_send_func']:
      # set them to self.
      super(_MessageDelegate, self).__setattr__(attr, value)
    else:
      setattr(self._msg, attr, value)

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

  @staticmethod
  def add_version_msg(build_config, kind, value):
    new_ver = build_config.versions.add()
    new_ver.kind = kind
    new_ver.value = value

  # property accessors
  @property
  def pubsub_project(self):
    return self._pubsub_project or default_project(self.m.build_menu.is_staging)

  @property
  def pubsub_topic(self):
    return self._pubsub_topic or default_topic()

  @property
  def build_type(self):
    return self._build_type

  @property
  def merged_build_report(self):
    return self._build_report

  def set_build_type(self, build_type, build_target):
    """Set the type for the build, must be set once and only once."""
    if not build_type in BuildReport.BuildType.values():
      raise ValueError("Invalid build type '%d', must be value defined in "
                       "BuildReport.BuildType" % build_type)
    if self._build_type is not None:
      raise RuntimeError("Build type can only be set once.")

    self._build_type = build_type
    self._build_target = build_target

  def __init__(self, properties, *args, **kwargs):
    super(BuildReportingApi, self).__init__(*args, **kwargs)
    self._properties = properties
    self._pubsub_project = properties.pubsub_project
    self._pubsub_topic = properties.pubsub_topic
    self._build_type = None
    self._build_target = None
    self._build_preamble_sent = False
    self._build_report = BuildReport()
    self._step_order = make_oneup()
    self._msg_counter = make_oneup()

  def py_MessageToJson(self, build_report):
    return json.dumps(
        MessageToDict(build_report), separators=(',', ':'), indent=2,
        sort_keys=True)

  def publish(self, build_report, raise_on_failed_publish=False):
    """Send a BuildReport to the pubsub topic.

    Also aggregates the published BuildReport which is then available through
    the merged_build_report property.

    Args:
      build_report (BuildReport): Instance to send to pub/sub.
      raise_on_failed_publish (bool): Should this publish fail, fail the whole
          build.

    Return:
      Reference to BuildReport input message.
    """
    if not isinstance(build_report, BuildReport):
      raise TypeError("Can only publish BuildReport messages.")

    build_report.buildbucket_id = self.m.buildbucket.build.id

    # If we haven't sent preamble info yet, add it to the first message.
    if not self._build_preamble_sent:
      if self._build_type is None:
        raise RuntimeError(
            "Build type must be set before sending first message.")

      parent = self.m.cros_tags.get_values('parent_buildbucket_id')
      if parent:
        build_report.parent.buildbucket_id = int(parent[0])

      build_report.type = self._build_type
      build_report.config.target.name = self._build_target
      self._build_preamble_sent = True

    # Add counter to message for ordering
    build_report.count = self._msg_counter()

    # Aggregate sent messages so we have a copy of the final status on our side.
    self._build_report.MergeFrom(build_report)

    with self.m.step.nest('build status pubsub update') as pres:
      # TODO(b/217973414): Replace with MessageToJson once we don't need to
      # fix the separator spacing between py2 and py3 MessageToJson.
      build_report_json = self.py_MessageToJson(self._build_report)
      pres.logs['message'] = build_report_json
      self.m.cloud_pubsub.publish_message(
          self.pubsub_project,
          self.pubsub_topic,
          # The publish-message binary requires that messages be base64 encoded to
          # avoid issues with binary data and strings.
          six.ensure_str(
              base64.b64encode(
                  self._build_report.SerializeToString(deterministic=True))),
          ordering_key=str(self.m.buildbucket.build.id or 'led-launch'),
          endpoint=PUBSUB_ENDPOINT,
          raise_on_failed_publish=raise_on_failed_publish,
      )

    return build_report

  def create_build_report(self):
    """Create BuildReport instance that can be .published().

    Return:
      _MessageDelegate wrapping BuildReport instance
    """
    build_report = BuildReport()
    return _MessageDelegate(
        build_report,
        lambda: self.publish(build_report),
    )

  def publish_status(self, status):
    """Publish and merge build status."""
    build_status = BuildReport.BuildStatus()
    build_status.value = status
    build_report = BuildReport()
    build_report.status.CopyFrom(build_status)
    self.publish(build_report)

  def publish_versions(self, gtv_response):
    """Publish and merge versions, sourced from a GetTargetVersionsRequest.

    Args:
      gtv_response (GetTargetVersionsResponse): Response to a build api request.

    Return:
      Nothing
    """
    build_report = BuildReport()
    config = build_report.config
    BuildReportingApi.add_version_msg(config,
                                      BuildConfig.VERSION_KIND_ASH_CHROME,
                                      gtv_response.chrome_version)
    BuildReportingApi.add_version_msg(config,
                                      BuildConfig.VERSION_KIND_MILESTONE,
                                      gtv_response.milestone_version)
    BuildReportingApi.add_version_msg(config, BuildConfig.VERSION_KIND_PLATFORM,
                                      gtv_response.platform_version)
    BuildReportingApi.add_version_msg(config, BuildConfig.VERSION_KIND_ARC,
                                      gtv_response.android_version)

    self.publish(build_report)

  def publish_build_artifact(
      self,
      artifact_type,
      gs_uri,
      sha256,
      created=None,
  ):
    """Publish and merge information about a created artifact.

    Args:
      artifact_type (BuildArtifact.Type): Type of the artifact.
      gs_uri (str): GS bucket URI for artifact (eg: gs://foo/bar/baz.tgz).
      sha256 (str): SHA256 hash for artifact.
      created (Datetime): Optional creation time (default: now).

    Raises:
      ValueError if gs_uri isn't properly formatted with gs:// prefix.

    Return:
      None
    """
    created = created or self.m.time.utcnow()

    if not gs_uri.startswith("gs://"):
      raise ValueError("GS bucket URI should start with gs:// prefix")

    build_report = BuildReport()
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
      raise_on_failed_publish=False,
  ):
    """Create a StepDetails instance to publish information for a step.

    Args:
      step_name (StepDetails.StepName): The predefined step name.
      start_time (Datetime): UTC datetime indicating step start time
      end_time (Datetime): UTC datetime indicating step end time
      status (StepDetails.Status): Step status (default: STATUS_RUNNING)
      raise_on_failed_publish (bool): Should this publish fail, fail the whole
          build.

    Return:
       _MessageDelegate wrapping StepDetails instance
    """
    build_report = BuildReport()

    step_details = build_report.steps.info[self.step_as_str(step_name)]
    step_details.order = self._step_order()
    step_details.status = status

    if start_time:
      step_details.runtime.begin.FromDatetime(start_time)

    if end_time:
      step_details.runtime.end.FromDatetime(end_time)

    return _MessageDelegate(
        step_details,
        lambda: self.publish(build_report,
                             raise_on_failed_publish=raise_on_failed_publish),
    )

  @contextlib.contextmanager
  def step_reporting(self, step_name, raise_on_failed_publish=False):
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
      step_name (StepDetails.StepName): The predefined step name.
      raise_on_failed_publish (bool): Should this publish fail, fail the whole
          build.
    Return:
      Handle which is used to set the step status.
    """

    class Handle(object):

      # The default status.
      status = self.STEP_SUCCESS

      @staticmethod
      def fail():
        Handle.status = self.STEP_FAILURE

      @staticmethod
      def infra_fail():
        Handle.status = self.STEP_INFRA_FAILURE

    # Publish the initial step status.
    step_info = self.create_step_info(
        step_name,
        start_time=self.m.time.utcnow(),
        raise_on_failed_publish=raise_on_failed_publish,
    )
    step_info.publish()

    try:
      yield Handle
    except InfraFailure:
      Handle.infra_fail()
      raise
    except StepFailure:
      Handle.fail()
      raise
    finally:
      # Publish the final step time.
      step_info.runtime.end.FromDatetime(self.m.time.utcnow())
      step_info.status = Handle.status
      step_info.publish()

  @contextlib.contextmanager
  def publish_to_gs(self, gs_path=None):
    """Create a context manager to automatically publish to gs.

    Args:
      gs_path (str): Path to the directory to upload the build report to.
        Defaults to build.menu.artifacts_gs_path().
    Return:
      Handle which is used to publish to GS.
    """

    class Handle(object):
      pass

    try:
      yield Handle
    finally:
      # Publish the final step time.
      self._upload_to_gs(gs_path or self.m.build_menu.artifacts_gs_path())

  def publish_build_target_and_model_metadata(self, branch, builder_metadata):
    """Publish and merge info about the build target and models of a build.

    Args:
      branch (str): The branch name (e.g. release-R97-14324.B).
      builder_metadata (GetBuilderMetadataResponse): Builder metadata from the
          build-api.
    """
    build_report = BuildReport()
    config = build_report.config

    config.branch.name = branch

    # First, set up the build target meta.
    helpers.set_build_target_metadata(config, builder_metadata)
    # Next, loop through all the models and set those up.
    for model_metadata in builder_metadata.model_metadata:
      config.models.append(helpers.create_model(model_metadata))
    self.publish(build_report)

  def publish_signed_build_metadata(self, signed_build_metadata_list):
    """Publish metadata about the signed build image(s).

    Args:
      signed_build_metadata_list (list[dict]): List of signed build metadata.
    """
    build_report = BuildReport()
    for signed_build_metadata in signed_build_metadata_list:
      status = self.m.cros_signing.get_status_from_instructions(
          signed_build_metadata)

      # If the status of the message is unavailable for some reason, short circuit
      # so we don't publish partial data.
      if not self.m.cros_signing.signing_succeeded(signed_build_metadata):
        continue

      build_report.signed_builds.append(
          helpers.create_signed_build(signed_build_metadata, status))

    self.publish(build_report)

  def _upload_to_gs(self, gs_path):
    """Serialize the build report and upload it to GS.

    Args:
      gs_path (str): Path to the directory to upload the build report to.
    """
    with self.m.step.nest('upload build report to GS') as presentation:
      tmp_dir = self.m.path.mkdtemp(prefix='LATEST')
      tmp_file = tmp_dir.join('build_report.json')
      build_report_json = self.py_MessageToJson(self._build_report)
      self.m.file.write_text('write buildreport json to tmp file', tmp_file,
                             build_report_json)
      self.m.gsutil(cmd=['cp', tmp_file, gs_path + '/build_report.json'],
                    name='write build_report.json to GS',
                    use_retry_wrapper=True)

      # TODO(b/217973414): Replace with native removeprefix call when we
      # don't have to support Python 2.
      def removeprefix(s, prefix):
        return s[len(prefix):] if s.startswith(prefix) else s

      presentation.links['gs upload dir'] = (
          'https://console.cloud.google.com/storage/browser/%s' %
          removeprefix(gs_path, 'gs://'))

  def publish_toolchain_info(self, toolchain_info):
    """Publish metadata about SDK/toolchain usage.

    Args:
      toolchain_info (cros_sdk.ToolchainInfo): Information about sdk/toolchain
        usage.
    """
    build_report = BuildReport()
    build_report.sdk_version = getattr(toolchain_info, 'sdk_version')
    build_report.toolchain_url = getattr(toolchain_info, 'toolchain_url')
    build_report.toolchains.extend(getattr(toolchain_info, 'toolchains'))

    self.publish(build_report)
