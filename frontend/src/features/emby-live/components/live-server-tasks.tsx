import { Square, Wrench } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { taskProgress } from "@/features/emby-live/presentation";
import { embyTaskActionKey } from "@/features/emby-live/task-action";
import type { EmbyLiveServer } from "@/features/emby-live/types";

type LiveServerTasksProps = {
  serverId: string;
  tasks: EmbyLiveServer["running_tasks"];
  stoppingTaskKeys: ReadonlySet<string>;
  taskStopErrors: Readonly<Record<string, string>>;
  onStopTask: (taskId: string, taskName?: string) => void;
};

function LiveServerTasks({
  serverId,
  tasks,
  stoppingTaskKeys,
  taskStopErrors,
  onStopTask,
}: LiveServerTasksProps) {
  if (!tasks.length) return null;

  return (
    <section className="emby-live-tasks" aria-label="Attività Emby in corso">
      <strong><Wrench size={15} aria-hidden="true" /> Attività in corso</strong>
      {tasks.map((task, index) => {
        const taskKey = task.id ? embyTaskActionKey(serverId, task.id) : "";
        const progress = taskProgress(task.progress);
        return (
          <div className="emby-live-task" key={task.id || `${task.name}-${index}`}>
            <div>
              <span>{task.name || "Operazione Emby"}</span>
              <small>{task.state || "In esecuzione"} · {progress}%</small>
            </div>
            <div className="emby-live-task-progress">
              <span><i style={{ width: `${progress}%` }} /></span>
              <Button
                type="button"
                requiresWriteAccess
                variant="ghost"
                size="icon"
                title="Ferma operazione"
                aria-label={`Ferma ${task.name || "operazione"}`}
                onClick={() => task.id && onStopTask(task.id, task.name)}
                disabled={!task.id || stoppingTaskKeys.has(taskKey)}
              >
                <Square size={13} aria-hidden="true" />
              </Button>
            </div>
            {taskKey && taskStopErrors[taskKey] ? (
              <p role="alert">{taskStopErrors[taskKey]}</p>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}

export { LiveServerTasks };
