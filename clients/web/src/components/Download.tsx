import { useMutation } from '@tanstack/react-query'
import { downloadZip } from '../api'
import { Spinner } from './ui'

export function DownloadButton({ id }: { id: string }) {
  const dl = useMutation({ mutationFn: () => downloadZip(id) })
  return (
    <span className="inline-grid gap-1">
      <button
        onClick={() => dl.mutate()}
        disabled={dl.isPending}
        className="inline-flex items-center justify-center gap-2 rounded-lg border border-line px-3 py-1.5 text-sm hover:border-slate-500 disabled:opacity-60"
      >
        {dl.isPending ? <Spinner /> : '↓'} ZIP (CSV + DuckDB)
      </button>
      {dl.error && <span className="text-xs text-rose-300">{dl.error.message}</span>}
    </span>
  )
}
