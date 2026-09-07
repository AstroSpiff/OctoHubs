import { useCallback, useRef, useState } from "react";

type DisclosureLease = {
  generation: number;
  ownerKey: string;
};

function useOwnerBoundDisclosure(ownerKey: string | null) {
  const owner = useRef({ generation: 0, key: ownerKey });
  if (owner.current.key !== ownerKey) {
    owner.current = { generation: owner.current.generation + 1, key: ownerKey };
  }
  const generation = owner.current.generation;
  const [lease, setLease] = useState<DisclosureLease | null>(null);

  const open = useCallback(() => {
    if (!ownerKey) return;
    setLease({ generation, ownerKey });
  }, [generation, ownerKey]);
  const close = useCallback(() => setLease(null), []);

  return {
    close,
    isOpen: Boolean(
      ownerKey
      && lease?.ownerKey === ownerKey
      && lease.generation === generation,
    ),
    open,
  };
}

export { useOwnerBoundDisclosure };
