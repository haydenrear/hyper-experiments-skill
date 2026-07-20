plugins {
    id("com.hayden.testgraphsdk.graph")
}

validationGraph {
    sourcesDir("sources")

    testGraph("hyperAllVariantClaudeObservability") {
        node("sources/hyper_repo_scaffolded.py")
        node("sources/hyper_variants_scaffolded.py")
        node("sources/hyper_default_short_run.py")
            .timeout("30m")
        node("sources/openevolve_claude_sonnet_short_run.py")
            .timeout("45m")
        node("sources/agentic_claude_sonnet_short_run.py")
            .timeout("45m")
        node("sources/hyper_observability_evidence.py")
            .timeout("10m")
    }
}
