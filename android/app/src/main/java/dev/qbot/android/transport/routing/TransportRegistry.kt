package dev.qbot.android.transport.routing

class TransportRegistry(
    val bindings: List<TransportAdapterBinding>,
) {
    init {
        val ids = bindings.map { it.snapshot().adapterId }
        require(ids.size == ids.toSet().size) {
            "transport adapter ids must be unique: " + ids
        }
    }

    val selector: TransportSelector =
        TransportSelector(bindings)

    fun binding(
        adapterId: String,
    ): TransportAdapterBinding? =
        bindings.firstOrNull {
            it.snapshot().adapterId == adapterId
        }

    fun snapshots(): List<TransportAdapterSnapshot> =
        selector.snapshots()
}
