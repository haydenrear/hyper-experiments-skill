plugins {
    id("com.hayden.testgraphsdk.graph")
}

validationGraph {
    sourcesDir("sources")

    testGraph("openevolveGeminiSmoke") {
        node("sources/hyper_repo_scaffolded.py")
        node("sources/openevolve_experiment_scaffolded.py")
        node("sources/openevolve_gemini_short_run.py")
            .timeout("45m")
        node("sources/openevolve_best_program_runs.py")
    }
}
