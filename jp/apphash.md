## production_android
com.sega.pjsekai (6.6.2, jp)
---
Reported Package: com.sega.pjsekai

|                                        app_hash|   app_region|  app_version|   ab_version|
|------------------------------------------------|-------------|-------------|-------------|
|            f70c7f71-042b-4763-9b80-0e8549d199b2|           jp|        6.6.2|        6.6.0|

- CLI Usage:

        sssekai abcache --app-platform android --app-region jp --app-version 6.6.2 --app-appHash f70c7f71-042b-4763-9b80-0e8549d199b2 --app-abVersion 6.6.0

- Python Usage:

        from sssekai.abcache import AbCacheConfig

        AbCacheConfig(
            app_region="jp",
            app_version="6.6.2",
            ab_version="6.6.0",
            app_hash="f70c7f71-042b-4763-9b80-0e8549d199b2",
            app_platform="android"
        )


## production_ios
com.sega.pjsekai (6.6.0, jp)
---
Reported Package: com.sega.pjsekai

|                                        app_hash|   app_region|  app_version|   ab_version|
|------------------------------------------------|-------------|-------------|-------------|
|            3b21f2ea-2e70-48b3-ad1f-3c6c6b1a5a26|           jp|        6.6.0|        6.6.0|

- CLI Usage:

        sssekai abcache --app-platform ios --app-region jp --app-version 6.6.0 --app-appHash 3b21f2ea-2e70-48b3-ad1f-3c6c6b1a5a26 --app-abVersion 6.6.0

- Python Usage:

        from sssekai.abcache import AbCacheConfig

        AbCacheConfig(
            app_region="jp",
            app_version="6.6.0",
            ab_version="6.6.0",
            app_hash="3b21f2ea-2e70-48b3-ad1f-3c6c6b1a5a26",
            app_platform="ios"
        )


