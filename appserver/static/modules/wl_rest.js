/**
 * wl_rest.js — REST helpers for Splunk splunkd proxy
 *
 * Builds the correct URL for the wl_manager custom REST endpoint
 * and provides GET/POST wrappers with proper output_mode and headers.
 * No app-state dependencies — pure HTTP helpers.
 */
define(["jquery"], function ($) {
    "use strict";

    function restUrl() {
        return Splunk.util.make_url(
            "/splunkd/__raw/services/custom/wl_manager"
        );
    }

    function restGet(params) {
        params = params || {};
        params.output_mode = "json";
        return $.ajax({
            url:      restUrl(),
            type:     "GET",
            data:     params,
            dataType: "json"
        });
    }

    function restPost(payload) {
        return $.ajax({
            url:         restUrl() + "?output_mode=json",
            type:        "POST",
            contentType: "application/json",
            data:        JSON.stringify(payload),
            dataType:    "json"
        });
    }

    return {
        restUrl:  restUrl,
        restGet:  restGet,
        restPost: restPost
    };
});
