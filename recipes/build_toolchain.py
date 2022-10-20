# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Builds and uploads the Chromium OS toolchain."""

import re

from PB.chromite.api.sdk import BuildPrebuiltsRequest
from PB.chromite.api.sdk import CreateBinhostCLsRequest
from PB.chromite.api.sdk import UploadPrebuiltPackagesRequest
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    "recipe_engine/step",
    "recipe_engine/time",
    "build_menu",
    "cros_build_api",
    "cros_sdk",
    "gerrit",
    "test_util",
]

PYTHON_VERSION_COMPATIBILITY = "PY3"

BUILDER = "chromeos/cq/chromeos-sdk-cq"
PREBUILT_UPLOAD_BUCKET = "gs://chromeos-prebuilt"
# The chromeos-sdk builder uses 'chroot' as VERSION_PREFIX.
# We use a different prefix to avoid conflicts.
VERSION_PREFIX = "build_toolchain"


def _insert_before_change_id(change, description, text):
  """Insert text before the Change-Id in a change's description.

  This effectively inserts text in description and returns the
  result, but with some tests and reporting that is factored
  into this function instead of being repeated at the point
  of use.

  Args:
    change: identifier for the change (shown in diagnostics)

    description: the original change description text

    text: text to insert

  Returns:
    the new description text
  """
  pos = description.find("\nChange-Id:")
  if pos == -1:
    raise StepFailure("No Change-Id found in %s %r" % (change, description))
  pos += 1  # We will insert text after the newline
  return description[:pos] + text + description[pos:]


def RunSteps(api):
  # Unlike normal CrOS builds, the SDK has no concept of pinned CrOS manifest
  # or specific Chrome version.  Use a datestamp instead.
  version = api.time.utcnow().strftime("%Y.%m.%d.%H%M%S")
  api.step.empty("new SDK version", step_text=version)

  with api.step.nest("identify key CLs"):
    # A toolchain update consists of a number of CLs that must be
    # landed together:
    #
    #  - The CL that makes the changes that necessitate a toolchain
    #    rebuild (e.g. a new LLVM, Rust, or library version).
    #
    #  - Binhost update CLs that point ChromiumOS at the newly-built
    #    toolchain.
    #
    #  - Optionally, additional CLs may be included.
    #
    # This step detects the binhost CLs (if present; they may not have
    # been generated yet) and chooses one non-binhost CL as the
    # "central" CL. The central CL will be made to cq-depend on the
    # binhost CLs once they have been generated.
    #
    # The mechanism for selecting the central CL is intentionally simple.
    #
    #  - Among the CLs that are part of this build, exactly one should
    #    be marked with Cq-Include-Trybots: {BUILDER}.
    #    That CL is the central CL.
    #
    # As a convenience, if no change has been marked with
    # Cq-Include-Trybots: {BUILDER}, but there is only one non-binhost
    # CL in the build, that CL is marked with Cq-Include-Trybots and
    # chosen as the central CL.
    #
    # TODO(b/251744856): Evaluate how well this works in practice and
    # see if a better strategy is called for.
    #
    central_cl = None
    binhost_cls = {}
    trybot_re = re.compile(r"^Cq-Include-Trybots: %s\b" % (re.escape(BUILDER),),
                           re.MULTILINE)
    patch_sets = api.gerrit.fetch_patch_sets(api.build_menu.gerrit_changes,
                                             include_commit_info=True)

    non_binhost_cls = []
    conflicting_cls = set()
    for change in patch_sets:
      if "updating FULL_BINHOST" in change.subject:
        binhost_cls[change.display_id] = change
      else:
        non_binhost_cls.append(change)
        if trybot_re.search(change.commit_info["message"]):
          if central_cl is not None:
            conflicting_cls.add(central_cl.display_id)
            conflicting_cls.add(change.display_id)
          else:
            central_cl = change

    if conflicting_cls:
      raise StepFailure(("multiple CLs have Cq-Include-Trybots: %s set"
                         ": %s") % (BUILDER, ", ".join(conflicting_cls)))

    if central_cl is None:
      # If there is only one non-binhost CL, make it the central CL.
      if len(non_binhost_cls) == 1:
        central_cl = non_binhost_cls[0]
        description = central_cl.commit_info["message"]
        trybots_str = "Cq-Include-Trybots: %s\n" % (BUILDER,)
        description = _insert_before_change_id(central_cl.display_id,
                                               description, trybots_str)
        api.gerrit.set_change_description(central_cl.to_gerrit_change_proto(),
                                          description)

    # After all this, there should be a central CL.
    if central_cl is None:
      raise StepFailure(
          ("Could not determine central CL."
           " Please set Cq-Include-Trybots: %s on exactly one CL.") %
          (BUILDER,))

  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():

    with api.step.nest("build SDK packages"):
      api.cros_build_api.SdkService.BuildPrebuilts(
          BuildPrebuiltsRequest(chroot=api.cros_sdk.chroot))

    with api.step.nest("upload prebuilt packages"):
      api.cros_build_api.SdkService.UploadPrebuiltPackages(
          UploadPrebuiltPackagesRequest(
              chroot=api.cros_sdk.chroot,
              prepend_version=VERSION_PREFIX,
              version=version,
              upload_location=PREBUILT_UPLOAD_BUCKET,
          ))

    with api.step.nest("create binhost CLs"):
      response = api.cros_build_api.SdkService.CreateBinhostCLs(
          CreateBinhostCLsRequest(
              prepend_version=VERSION_PREFIX,
              version=version,
              upload_location=PREBUILT_UPLOAD_BUCKET,
          ))
      new_binhost_cls = response.cls

    with api.step.nest("cq-depend on binhost CLs"):
      # If the central CL cq-depends on binhost CLs already, remove
      # those dependencies.
      gerrit_change = central_cl.to_gerrit_change_proto()
      description = api.gerrit.get_change_description(gerrit_change)
      binhost_re = "|".join(re.escape(text) for text in binhost_cls.keys())
      description = re.sub(
          r"^Cq-Depend: (?:%s)$" % (binhost_re,),
          "",
          description,
          flags=re.MULTILINE,
      )

      # Add cq-depends on the new binhost CLs.
      # new_binhost_cls has the URIs of the binhost CLs.
      # We need the short_host:change_id representation.
      binhost_changes = [
          api.gerrit.parse_gerrit_change(cl) for cl in new_binhost_cls
      ]
      binhost_patchsets = api.gerrit.fetch_patch_sets(binhost_changes)
      depends_str = "".join("Cq-Depend: %s\n" % (change.display_id,)
                            for change in binhost_patchsets)
      description = _insert_before_change_id(central_cl.display_id, description,
                                             depends_str)
      api.gerrit.set_change_description(gerrit_change, description)


def GenTests(api):
  single_change_with_trybots = GerritChange(
      change=101,
      project="cromiumos/overlays/chromiumos-overlay",
      host="chromium-review.googlesource.com",
      patchset=1,
  )

  single_change_without_trybots = GerritChange(
      change=102,
      project="cromiumos/overlays/chromiumos-overlay",
      host="chromium-review.googlesource.com",
      patchset=1,
  )

  another_change_without_trybots = GerritChange(
      change=103,
      project="cromiumos/overlays/chromiumos-overlay",
      host="chromium-review.googlesource.com",
      patchset=1,
  )

  prebuilt_binhost_change = GerritChange(
      change=104,
      project="cromiumos/overlays/chromiumos-overlay",
      host="chromium-review.googlesource.com",
      patchset=1,
  )

  missing_change_id = GerritChange(
      change=105,
      project="cromiumos/overlays/chromiumos-overlay",
      host="chromium-review.googlesource.com",
      patchset=1,
  )

  another_change_with_trybots = GerritChange(
      change=106,
      project="cromiumos/overlays/chromiumos-overlay",
      host="chromium-review.googlesource.com",
      patchset=1,
  )

  fetch_changes_responses = {
      101: {
          "change_id": "101",
          "revision_info": {
              "commit": {
                  "message":
                      ("toolchain update test change\n"
                       "\nCq-Include-Trybots: chromeos/cq/chromeos-sdk-cq\n"
                       "Change-Id: Xabc\n"),
              },
          },
      },
      102: {
          "change_id": "102",
          "revision_info": {
              "commit": {
                  "message": ("simple toolchain update test change\n"
                              "\nChange-Id: Xdfg\n"),
              },
          },
      },
      103: {
          "change_id": "103",
          "revision_info": {
              "commit": {
                  "message": ("another change without trybots\n"
                              "\nChange-Id: Xghj\n"),
              },
          },
      },
      104: {
          "change_id": "104",
          "subject": "prebuilt.conf: updating FULL_BINHOST",
          "revision_info": {
              "commit": {
                  "message": ("prebuilt.conf: updating FULL_BINHOST\n"
                              "\nChange-Id: Xjxl\n"),
              },
          },
      },
      105: {
          "change_id": "105",
          "subject": "no change id",
          "revision_info": {
              "commit": {
                  "message": "change without change-id\n",
              },
          },
      },
      106: {
          "change_id": "106",
          "subject": "another change with trybots",
          "revision_info": {
              "commit": {
                  "message":
                      ("this change also has the trybots footer\n"
                       "\nCq-Include-Trybots: chromeos/cq/chromeos-sdk-cq\n"
                       "\nChange-Id: Xgli\n"),
              },
          },
      },
  }

  def builder_args(**kwargs):
    """Generate a test build."""
    kwargs.setdefault("cq", True)
    return kwargs

  yield api.build_menu.test(
      "no-cl",
      api.gerrit.set_gerrit_fetch_changes_response("identify key CLs", [],
                                                   fetch_changes_responses),
      api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.DoesNotRun, "build SDK packages"),
      api.post_check(post_process.DoesNotRun, "upload prebuilt packages"),
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[]))

  yield api.build_menu.test(
      "no-central-cl",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_without_trybots, another_change_without_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.DoesNotRun, "build SDK packages"),
      api.post_check(post_process.DoesNotRun, "upload prebuilt packages"),
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[
          single_change_without_trybots,
          another_change_without_trybots,
      ]))

  yield api.build_menu.test(
      "no-change-id",
      api.gerrit.set_gerrit_fetch_changes_response("identify key CLs",
                                                   [missing_change_id],
                                                   fetch_changes_responses),
      api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.DoesNotRun, "build SDK packages"),
      api.post_check(post_process.DoesNotRun, "upload prebuilt packages"),
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[missing_change_id]))

  yield api.build_menu.test(
      "multiple-trybots-cls",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_with_trybots, another_change_with_trybots],
          fetch_changes_responses),
      api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.DoesNotRun, "build SDK packages"),
      api.post_check(post_process.DoesNotRun, "upload prebuilt packages"),
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[
          single_change_with_trybots, another_change_with_trybots
      ]))

  yield api.build_menu.test(
      "sucessful-run",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_with_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.MustRun, "build SDK packages"),
      api.post_check(post_process.MustRun, "upload prebuilt packages"),
      api.post_check(post_process.MustRun, "create binhost CLs"),
      api.post_check(post_process.MustRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]))

  yield api.build_menu.test(
      "sucessful-run-no-include-trybots",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_without_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.MustRun, "build SDK packages"),
      api.post_check(post_process.MustRun, "upload prebuilt packages"),
      api.post_check(post_process.MustRun, "create binhost CLs"),
      api.post_check(post_process.MustRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_without_trybots]))

  yield api.build_menu.test(
      "sucessful-run-with-binhost-cl",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_without_trybots, prebuilt_binhost_change],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.MustRun, "build SDK packages"),
      api.post_check(post_process.MustRun, "upload prebuilt packages"),
      api.post_check(post_process.MustRun, "create binhost CLs"),
      api.post_check(post_process.MustRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[
          single_change_without_trybots,
          prebuilt_binhost_change,
      ]))

  yield api.build_menu.test(
      "build_sdk_packages-failed",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_with_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.MustRun, "identify key CLs"),
      api.post_check(post_process.MustRun, "build SDK packages"),
      api.post_check(post_process.DoesNotRun, "upload prebuilt packages"),
      api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return("build SDK packages",
                                          "SdkService/BuildPrebuilts",
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]))

  yield api.build_menu.test(
      "upload_prebuilt_packages-failed",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_with_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.DoesNotRun, "create binhost CLs"),
      api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return(
          "upload prebuilt packages",
          "SdkService/UploadPrebuiltPackages",
          retcode=1,
      ), api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]))

  yield api.build_menu.test(
      "create-binhost-cls-failed",
      api.gerrit.set_gerrit_fetch_changes_response(
          "identify key CLs",
          [single_change_with_trybots],
          fetch_changes_responses,
      ), api.post_check(post_process.DoesNotRun, "cq-depend on binhost CLs"),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return("create binhost CLs",
                                          "SdkService/CreateBinhostCLs",
                                          retcode=1),
      api.post_process(post_process.DropExpectation),
      **builder_args(gerrit_changes=[single_change_with_trybots]))
