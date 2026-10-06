# Client builds

Hosted build, signing and update-check workflows for FairyStack's native clients
(Mac, Windows, iOS, Android) and Voice Feed for Mac.

This repository contains workflows and generic build helpers only. Client source is
proprietary and private: each run checks out one private source snapshot with a
read-only deploy key, deletes its Git metadata, and uploads only signed binaries and
receipts. Do not add client source, source archives or source artifacts here.

Official downloads: https://fairystack.com/companions
