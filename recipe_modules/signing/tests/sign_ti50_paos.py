# -*- coding: utf-8 -*-
# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for signing_operation."""

from google.protobuf.json_format import MessageToDict

from PB.chromiumos import build_report as build_report_pb2
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/step',
    'signing',
    'signing_utils',
]

PASSED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED
FAILED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_FAILED


def RunSteps(api: RecipeApi):
  # Call signing.
  api.signing_utils.custom_artifact_version = 'ti50/nt-signed/1234'
  api.signing.sign_ti50_paos(api.path.start_dir / 'shellball-dir', "project",
                             "keyring", "key", "file.tar")


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(gs_upload_bucket='chromeos-releases'))
          }),
      api.post_check(post_process.MustRun,
                     'call chromite.api.SigningService/SignTi50Paos'),
      api.post_check(
          post_process.StepCommandContains,
          'upload signed artifact to chromeos-releases bucket.gsutil cp', [
              '[CLEANUP]/signing-dir_tmp_1/file.tar',
              'gs://chromeos-releases/ti50/nt-signed/1234/'
          ]), api.post_process(post_process.DropExpectation))
